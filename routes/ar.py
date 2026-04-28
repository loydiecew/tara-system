from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date
from models.database import get_db
from models.audit import log_audit

ar_bp = Blueprint('ar', __name__)

@ar_bp.route('/ar')
def ar():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
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
    
    # Get all invoices with customer names (excluding soft-deleted)
    cursor.execute("""
        SELECT i.*, c.name as customer_name 
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        JOIN users u ON i.user_id = u.id
        WHERE u.business_id = %s AND i.deleted_at IS NULL
        ORDER BY i.due_date ASC
    """, (business_id,))
    invoices = cursor.fetchall()
    
    # Calculate total outstanding (unpaid, not deleted) for this business
    cursor.execute("""
        SELECT SUM(i.amount) as total FROM invoices i
        JOIN users u ON i.user_id = u.id
        WHERE u.business_id = %s AND i.status = 'unpaid' AND i.deleted_at IS NULL
    """, (business_id,))
    total_outstanding = cursor.fetchone()['total'] or 0
    
    cursor.close()
    db.close()
    
    return render_template('ar.html',
                         username=session['username'],
                         customers=customers,
                         invoices=invoices,
                         total_outstanding=total_outstanding)

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
        status = request.form['status']
        description = request.form.get('description', '')
        
        cursor.execute("""
            UPDATE invoices 
            SET customer_id = %s, amount = %s, due_date = %s, invoice_number = %s, status = %s, description = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (customer_id, amount, due_date, invoice_number, status, description, invoice_id, session['user_id']))
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
    
    # Insert invoice
    cursor.execute("""
        INSERT INTO invoices (user_id, customer_id, invoice_number, amount, description, due_date)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (session['user_id'], customer_id, invoice_number, amount, description, due_date))
    db.commit()
    
    # Create journal entry for Pro/Enterprise users (using same connection)
    if session.get('plan') in ['pro', 'enterprise']:
        # Use a new cursor on the same connection
        cursor2 = db.cursor(dictionary=True)
        
        # Get account IDs
        cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '1100'")  # Accounts Receivable
        ar_account = cursor2.fetchone()
        cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '4000'")  # Sales Revenue
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

@ar_bp.route('/pay_invoice/<int:invoice_id>')
def pay_invoice(invoice_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT i.*, c.name as customer_name 
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.id = %s AND i.user_id = %s
    """, (invoice_id, session['user_id']))
    invoice = cursor.fetchone()
    
    if invoice and invoice['status'] == 'unpaid':
        cursor.execute("""
            UPDATE invoices SET status = 'paid' 
            WHERE id = %s AND user_id = %s
        """, (invoice_id, session['user_id']))
        
        # Create cash transaction
        cursor.execute("""
            INSERT INTO transactions (user_id, description, amount, type, category, transaction_date)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            session['user_id'],
            f"Payment received from {invoice['customer_name']} - Invoice #{invoice['invoice_number'] or invoice['id']}",
            invoice['amount'],
            'income',
            'Sales',
            date.today()
        ))
        
        # Create journal entry to clear AR (Pro users only)
        if session.get('plan') in ['pro', 'enterprise']:
            cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '1000'")  # Cash
            cash_account = cursor.fetchone()
            cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '1100'")  # AR
            ar_account = cursor.fetchone()
            
            if cash_account and ar_account:
                from routes.cash import create_journal_entry
                lines = [
                    {'account_id': cash_account['id'], 'debit': invoice['amount'], 'credit': 0},
                    {'account_id': ar_account['id'], 'debit': 0, 'credit': invoice['amount']}
                ]
                create_journal_entry(
                    user_id=session['user_id'],
                    entry_date=date.today(),
                    description=f"Payment received for Invoice #{invoice['invoice_number'] or invoice['id']}",
                    lines=lines
                )
        
        db.commit()
    
    cursor.close()
    db.close()
    
    return redirect(url_for('ar.ar'))