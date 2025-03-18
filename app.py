from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pdfkit
import io

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bills.db'
db = SQLAlchemy(app)

# PDF configuration
config = pdfkit.configuration(wkhtmltopdf=r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe')

class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(10), nullable=False)
    bill_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    total_amount = db.Column(db.Float, nullable=False)
    remaining_amount = db.Column(db.Float, nullable=False)
    items = db.relationship('BillItem', backref='bill', lazy=True)
    payments = db.relationship('Payment', backref='bill', lazy=True)

class BillItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bill.id'), nullable=False)
    item_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bill.id'), nullable=False)
    payment_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    amount = db.Column(db.Float, nullable=False)

@app.route('/')
def index():
    bills = Bill.query.order_by(Bill.bill_date.desc()).all()
    return render_template('bill_list.html', bills=bills)

@app.route('/generate_bill', methods=['GET', 'POST'])
def generate_bill():
    if request.method == 'POST':
        customer_name = request.form['customer_name']
        phone_number = request.form['phone_number']
        bill_date = datetime.strptime(request.form['bill_date'], '%Y-%m-%d')
        total_amount = float(request.form['total_amount'])
        initial_payment = float(request.form['initial_payment'])
        remaining_amount = float(request.form['remaining_amount'])

        bill = Bill(
            customer_name=customer_name,
            phone_number=phone_number,
            bill_date=bill_date,
            total_amount=total_amount,
            remaining_amount=remaining_amount
        )
        db.session.add(bill)
        db.session.flush()

        # Add items
        items = request.form.getlist('item_name[]')
        quantities = request.form.getlist('quantity[]')
        prices = request.form.getlist('price[]')
        
        for i in range(len(items)):
            item = BillItem(
                bill_id=bill.id,
                item_name=items[i],
                quantity=int(quantities[i]),
                price=float(prices[i]),
                subtotal=float(prices[i]) * int(quantities[i])
            )
            db.session.add(item)

        # Add initial payment if any
        if initial_payment > 0:
            payment = Payment(
                bill_id=bill.id,
                amount=initial_payment
            )
            db.session.add(payment)

        db.session.commit()
        return redirect(url_for('index'))

    return render_template('generate_bill.html')

@app.route('/edit_bill/<int:bill_id>', methods=['GET', 'POST'])
def edit_bill(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    if request.method == 'POST':
        old_total = bill.total_amount
        new_total = float(request.form['total_amount'])
        difference = new_total - old_total
        
        bill.customer_name = request.form['customer_name']
        bill.phone_number = request.form['phone_number']
        bill.bill_date = datetime.strptime(request.form['bill_date'], '%Y-%m-%d')
        bill.total_amount = new_total
        bill.remaining_amount = bill.remaining_amount + difference

        for item in bill.items:
            db.session.delete(item)

        items = request.form.getlist('item_name[]')
        quantities = request.form.getlist('quantity[]')
        prices = request.form.getlist('price[]')
        
        for i in range(len(items)):
            item = BillItem(
                bill_id=bill.id,
                item_name=items[i],
                quantity=int(quantities[i]),
                price=float(prices[i]),
                subtotal=float(prices[i]) * int(quantities[i])
            )
            db.session.add(item)

        db.session.commit()
        return redirect(url_for('index'))
    
    return render_template('edit_bill.html', bill=bill)

@app.route('/pay_bill/<int:bill_id>', methods=['POST'])
def pay_bill(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    payment_amount = float(request.form['payment_amount'])
    
    if payment_amount <= bill.remaining_amount:
        payment = Payment(bill_id=bill.id, amount=payment_amount)
        bill.remaining_amount -= payment_amount
        db.session.add(payment)
        db.session.commit()
        
    return redirect(url_for('index'))

@app.route('/payment_history/<int:bill_id>')
def payment_history(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    return render_template('payment_history.html', bill=bill)

@app.route('/download_bill/<int:bill_id>')
def download_bill(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    html = render_template('bill_pdf.html', bill=bill)
    
    options = {
        'page-size': 'A4',
        'margin-top': '0.75in',
        'margin-right': '0.75in',
        'margin-bottom': '0.75in',
        'margin-left': '0.75in',
        'encoding': 'UTF-8',
        'no-outline': None,
        'enable-local-file-access': None
    }
    
    pdf = pdfkit.from_string(html, False, options=options, configuration=config)
    
    # Create filename using customer name and bill ID
    safe_name = "".join(x for x in bill.customer_name if x.isalnum() or x.isspace()).strip()
    filename = f'{safe_name}_bill_{bill.id}.pdf'
    
    response = send_file(
        io.BytesIO(pdf),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )
    return response

@app.route('/delete_bill/<int:bill_id>', methods=['POST'])
def delete_bill(bill_id):
    try:
        bill = Bill.query.get_or_404(bill_id)
        if bill.remaining_amount == 0:
            # Delete related records first
            BillItem.query.filter_by(bill_id=bill.id).delete()
            Payment.query.filter_by(bill_id=bill.id).delete()
            # Then delete the bill
            db.session.delete(bill)
            db.session.commit()
            flash('Bill deleted successfully', 'success')
        else:
            flash('Cannot delete unpaid bill', 'danger')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting bill', 'danger')
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)