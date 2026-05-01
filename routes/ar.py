from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from datetime import date, timedelta
from models.database import get_db
from models.audit import log_audit

ar_bp = Blueprint('ar', __name__)

@ar_bp.route('/ar')
def ar():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('role') not in ['admin', 'owner']:
        flash('Access restricted to admins and owners.', 'error')
        return redirect(url_for('dashboard.dashboard'))

    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get all customers for this business (excluding soft-deleted)
    cursor.execute("""
        SELECT c.* FROM customers c
        JOIN users u ON c.user_id = u.id
        WHERE u.business_id = %s AND c.deleted_at IS NULL
    """, (business_id,))
    customers = cursor.fetchall()
    
    # Get all invoices with customer names and total paid (excluding soft-deleted)
    cursor.execute("""
        SELECT i.*, c.name as customer_name,
            COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = i.id), 0) as paid_amount
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        JOIN users u ON i.user_id = u.id
        WHERE u.business_id = %s AND i.deleted_at IS NULL
        ORDER BY i.due_date ASC
    """, (business_id,))
    invoices = cursor.fetchall()
    
    # Calculate remaining balance for each invoice and update status/aging
    today = date.today()
    for inv in invoices:
        inv['remaining'] = float(inv['amount']) - float(inv['paid_amount'])
        
        # Determine status
        if inv['remaining'] <= 0:
            inv['status'] = 'paid'
        elif float(inv['paid_amount']) > 0:
            inv['status'] = 'partially_paid'
        else:
            inv['status'] = 'unpaid'
        
        # Aging badge
        if inv['status'] != 'paid':
            due = inv['due_date']
            if isinstance(due, str):
                due = date.fromisoformat(str(due))
            days_overdue = (today - due).days if due else 0
            if days_overdue <= 0:
                inv['aging'] = 'current'
                inv['aging_label'] = 'Current'
                inv['aging_class'] = 'badge-info'
            elif days_overdue <= 30:
                inv['aging'] = '30days'
                inv['aging_label'] = '1-30 days'
                inv['aging_class'] = 'badge-warning'
            elif days_overdue <= 60:
                inv['aging'] = '60days'
                inv['aging_label'] = '31-60 days'
                inv['aging_class'] = 'badge-warning'
            else:
                inv['aging'] = '90plus'
                inv['aging_label'] = '60+ days'
                inv['aging_class'] = 'badge-danger'
        else:
            inv['aging'] = 'paid'
            inv['aging_label'] = 'Paid'
            inv['aging_class'] = 'badge-success'
    
    # Total outstanding (remaining balance across all unpaid/partial invoices)
    total_outstanding = sum(inv['remaining'] for inv in invoices if inv['status'] != 'paid')
    
    cursor.close()
    db.close()
    
    return render_template('ar.html',
                         username=session['username'],
                         customers=customers,
                         invoices=invoices,
                         total_outstanding=total_outstanding,
                         today=date.today().isoformat())

@ar_bp.route('/delete_invoice/<int:invoice_id>')
def delete_invoice(invoice_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM invoices WHERE id = %s AND user_id = %s", 
                   (invoice_id, session['user_id']))
    invoice = cursor.fetchone()
    
    if invoice and invoice.get('deleted_at') is None:
        cursor.execute("""
            UPDATE invoices SET deleted_at = NOW() 
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (invoice_id, session['user_id']))
        db.commit()
        
        log_audit(session['user_id'], session['username'], 'DELETE', 'invoices', 
                  invoice_id, old_values=invoice)
    
    cursor.close()
    db.close()
    
    return redirect(url_for('ar.ar'))

@ar_bp.route('/edit_invoice/<int:invoice_id>', methods=['GET', 'POST'])
def edit_invoice(invoice_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("SELECT * FROM invoices WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                       (invoice_id, session['user_id']))
        old_invoice = cursor.fetchone()
        
        if not old_invoice:
            cursor.close()
            db.close()
            return redirect(url_for('ar.ar'))
        
        customer_id = request.form['customer_id']
        amount = float(request.form['amount'])
        due_date = request.form['due_date']
        invoice_number = request.form.get('invoice_number', '')
        description = request.form.get('description', '')
        
        cursor.execute("""
            UPDATE invoices 
            SET customer_id = %s, amount = %s, due_date = %s, invoice_number = %s, description = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (customer_id, amount, due_date, invoice_number, description, invoice_id, session['user_id']))
        db.commit()
        
        cursor.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
        new_invoice = cursor.fetchone()
        
        log_audit(session['user_id'], session['username'], 'UPDATE', 'invoices', 
                  invoice_id, old_values=old_invoice, new_values=new_invoice)
        
        cursor.close()
        db.close()
        return redirect(url_for('ar.ar'))
    
    # GET request - show edit form
    cursor.execute("""
        SELECT i.*, c.name as customer_name 
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.id = %s AND i.user_id = %s AND i.deleted_at IS NULL
    """, (invoice_id, session['user_id']))
    invoice = cursor.fetchone()
    
    if not invoice:
        cursor.close()
        db.close()
        return redirect(url_for('ar.ar'))
    
    business_id = session.get('business_id', session['user_id'])
    cursor.execute("""
        SELECT c.id, c.name FROM customers c
        JOIN users u ON c.user_id = u.id
        WHERE u.business_id = %s AND c.deleted_at IS NULL
    """, (business_id,))
    customers = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('edit_invoice.html',
                         username=session['username'],
                         invoice=invoice,
                         customers=customers)

@ar_bp.route('/add_customer', methods=['POST'])
def add_customer():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    name = request.form['name']
    email = request.form.get('email', '')
    phone = request.form.get('phone', '')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO customers (user_id, name, email, phone)
        VALUES (%s, %s, %s, %s)
    """, (session['user_id'], name, email, phone))
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Customer "{name}" added successfully!', 'success')
    return redirect(url_for('ar.ar'))

@ar_bp.route('/add_invoice', methods=['POST'])
def add_invoice():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    customer_id = request.form['customer_id']
    amount = float(request.form['amount'])
    due_date = request.form['due_date']
    description = request.form.get('description', '')
    invoice_number = request.form.get('invoice_number', f"INV-{customer_id}-{due_date}")
    
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        INSERT INTO invoices (user_id, customer_id, invoice_number, amount, description, due_date)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (session['user_id'], customer_id, invoice_number, amount, description, due_date))
    db.commit()
    
    if session.get('plan') in ['pro', 'enterprise']:
        cursor2 = db.cursor(dictionary=True)
        cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '1100'")
        ar_account = cursor2.fetchone()
        cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '4000'")
        revenue_account = cursor2.fetchone()
        if ar_account and revenue_account:
            from routes.cash import create_journal_entry
            lines = [
                {'account_id': ar_account['id'], 'debit': amount, 'credit': 0},
                {'account_id': revenue_account['id'], 'debit': 0, 'credit': amount}
            ]
            create_journal_entry(
                user_id=session['user_id'],
                entry_date=due_date,
                description=f"Invoice #{invoice_number} - {description or 'Sale to customer'}",
                lines=lines
            )
        cursor2.close()
    
    cursor.close()
    db.close()
    
    flash(f'Invoice #{invoice_number} created successfully!', 'success')
    return redirect(url_for('ar.ar'))

@ar_bp.route('/record_payment/<int:invoice_id>', methods=['POST'])
def record_payment(invoice_id):
    """Record a payment (full or partial) against an invoice"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    amount = float(request.form['amount'])
    payment_date = request.form.get('payment_date', date.today())
    payment_method = request.form.get('payment_method', 'cash')
    reference_number = request.form.get('reference_number', '')
    notes = request.form.get('notes', '')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get invoice
    cursor.execute("""
        SELECT i.*, c.name as customer_name 
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.id = %s AND i.user_id = %s AND i.deleted_at IS NULL
    """, (invoice_id, session['user_id']))
    invoice = cursor.fetchone()
    
    if not invoice:
        cursor.close()
        db.close()
        flash('Invoice not found', 'error')
        return redirect(url_for('ar.ar'))
    
    # Calculate total already paid
    cursor.execute("SELECT COALESCE(SUM(amount), 0) as total_paid FROM payments WHERE invoice_id = %s", (invoice_id,))
    total_paid = float(cursor.fetchone()['total_paid'])
    remaining = float(invoice['amount']) - total_paid
    
    if amount > remaining:
        amount = remaining  # Cap at remaining balance
    
    if amount <= 0:
        cursor.close()
        db.close()
        flash('No remaining balance on this invoice', 'error')
        return redirect(url_for('ar.ar'))
    
    # Insert payment
    cursor.execute("""
        INSERT INTO payments (user_id, invoice_id, amount, payment_date, payment_method, reference_number, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (session['user_id'], invoice_id, amount, payment_date, payment_method, reference_number, notes))
    
    # Create cash transaction for this payment
    cursor.execute("""
        INSERT INTO transactions (user_id, description, amount, type, category, transaction_date)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        session['user_id'],
        f"Payment from {invoice['customer_name']} - {invoice['invoice_number'] or 'INV-'+str(invoice_id)} ({payment_method})",
        amount,
        'income',
        'Accounts Receivable',
        payment_date
    ))
    
    # Journal entry for Pro users
    if session.get('plan') in ['pro', 'enterprise']:
        cursor2 = db.cursor(dictionary=True)
        cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '1000'")
        cash_account = cursor2.fetchone()
        cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '1100'")
        ar_account = cursor2.fetchone()
        if cash_account and ar_account:
            from routes.cash import create_journal_entry
            lines = [
                {'account_id': cash_account['id'], 'debit': amount, 'credit': 0},
                {'account_id': ar_account['id'], 'debit': 0, 'credit': amount}
            ]
            create_journal_entry(
                user_id=session['user_id'],
                entry_date=payment_date,
                description=f"Payment for {invoice['invoice_number'] or 'INV-'+str(invoice_id)} ({payment_method})",
                lines=lines
            )
        cursor2.close()
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Payment of ₱{amount:,.2f} recorded!', 'success')
    return redirect(url_for('ar.ar'))

@ar_bp.route('/invoice_payments/<int:invoice_id>')
def invoice_payments(invoice_id):
    """Get payment history for an invoice (JSON)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT p.* FROM payments p
        WHERE p.invoice_id = %s AND p.user_id = %s
        ORDER BY p.payment_date DESC
    """, (invoice_id, session['user_id']))
    payments = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    for p in payments:
        if 'payment_date' in p and hasattr(p['payment_date'], 'isoformat'):
            p['payment_date'] = p['payment_date'].isoformat()
    
    return jsonify({'payments': payments})

@ar_bp.route('/receipt/payment/<int:payment_id>')
def payment_receipt(payment_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get payment with invoice and customer details
    cursor.execute("""
        SELECT p.*, i.invoice_number, i.amount as invoice_total, c.name as customer_name
        FROM payments p
        LEFT JOIN invoices i ON p.invoice_id = i.id
        LEFT JOIN customers c ON i.customer_id = c.id
        WHERE p.id = %s AND p.user_id = %s
    """, (payment_id, session['user_id']))
    payment = cursor.fetchone()
    
    if not payment:
        cursor.close()
        db.close()
        flash('Payment record not found', 'error')
        return redirect(url_for('ar.ar'))
    
    # Get business owner details
    cursor.execute("""
        SELECT username, business_name, business_id FROM users
        WHERE business_id = %s AND role IN ('admin', 'owner')
        LIMIT 1
    """, (business_id,))
    owner = cursor.fetchone()
    
    cursor.close()
    db.close()
    
    business_name = owner['business_name'] if owner and owner.get('business_name') else session.get('business_name', 'My Business')
    business_id_num = owner['business_id'] if owner and owner.get('business_id') else business_id
    
    receipt_number = f"RCPT-{payment_id:06d}"
    today = date.today()
    
    return render_template('payment_receipt.html',
                         payment=payment,
                         business_name=business_name,
                         business_id=business_id_num,
                         receipt_number=receipt_number,
                         today=today,
                         username=session['username'])