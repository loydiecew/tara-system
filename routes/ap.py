from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from datetime import date, timedelta
from models.database import get_db
from models.audit import log_audit

ap_bp = Blueprint('ap', __name__)

@ap_bp.route('/ap')
def ap():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('role') not in ['admin', 'owner']:
        flash('Access restricted to admins and owners.', 'error')
        return redirect(url_for('dashboard.dashboard'))
        
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get all suppliers for this business (excluding soft-deleted)
    cursor.execute("""
        SELECT s.* FROM suppliers s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.deleted_at IS NULL
    """, (business_id,))
    suppliers = cursor.fetchall()
    
    # Get all bills with supplier names and total paid (excluding soft-deleted)
    cursor.execute("""
        SELECT b.*, s.name as supplier_name,
            COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.bill_id = b.id), 0) as paid_amount
        FROM bills b
        JOIN suppliers s ON b.supplier_id = s.id
        JOIN users u ON b.user_id = u.id
        WHERE u.business_id = %s AND b.deleted_at IS NULL
        ORDER BY b.due_date ASC
    """, (business_id,))
    bills = cursor.fetchall()
    
    # Calculate remaining balance and update status/aging
    today = date.today()
    for bill in bills:
        bill['remaining'] = float(bill['amount']) - float(bill['paid_amount'])
        
        # Determine status
        if bill['remaining'] <= 0:
            bill['status'] = 'paid'
        elif float(bill['paid_amount']) > 0:
            bill['status'] = 'partially_paid'
        else:
            bill['status'] = 'unpaid'
        
        # Due date tracking
        if bill['status'] != 'paid':
            due = bill['due_date']
            if isinstance(due, str):
                due = date.fromisoformat(str(due))
            days_until = (due - today).days if due else 0
            if days_until < 0:
                bill['due_label'] = f'Overdue by {abs(days_until)} days'
                bill['due_class'] = 'badge-danger'
            elif days_until <= 7:
                bill['due_label'] = f'Due in {days_until} days'
                bill['due_class'] = 'badge-warning'
            else:
                bill['due_label'] = f'Due in {days_until} days'
                bill['due_class'] = 'badge-info'
        else:
            bill['due_label'] = 'Paid'
            bill['due_class'] = 'badge-success'
    
    # Total outstanding
    total_outstanding = sum(bill['remaining'] for bill in bills if bill['status'] != 'paid')
    
    cursor.close()
    db.close()
    
    return render_template('ap.html',
                         username=session['username'],
                         suppliers=suppliers,
                         bills=bills,
                         total_outstanding=total_outstanding,
                         today=date.today().isoformat())

@ap_bp.route('/delete_bill/<int:bill_id>')
def delete_bill(bill_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM bills WHERE id = %s AND user_id = %s", 
                   (bill_id, session['user_id']))
    bill = cursor.fetchone()
    
    if bill and bill.get('deleted_at') is None:
        cursor.execute("""
            UPDATE bills SET deleted_at = NOW() 
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (bill_id, session['user_id']))
        db.commit()
        log_audit(session['user_id'], session['username'], 'DELETE', 'bills', 
                  bill_id, old_values=bill)
    
    cursor.close()
    db.close()
    
    return redirect(url_for('ap.ap'))

@ap_bp.route('/edit_bill/<int:bill_id>', methods=['GET', 'POST'])
def edit_bill(bill_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("SELECT * FROM bills WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                       (bill_id, session['user_id']))
        old_bill = cursor.fetchone()
        
        if not old_bill:
            cursor.close()
            db.close()
            return redirect(url_for('ap.ap'))
        
        supplier_id = request.form['supplier_id']
        amount = float(request.form['amount'])
        due_date = request.form['due_date']
        description = request.form.get('description', '')
        bill_number = request.form.get('bill_number', '')
        
        cursor.execute("""
            UPDATE bills 
            SET supplier_id = %s, amount = %s, due_date = %s, description = %s, bill_number = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (supplier_id, amount, due_date, description, bill_number, bill_id, session['user_id']))
        db.commit()
        
        cursor.execute("SELECT * FROM bills WHERE id = %s", (bill_id,))
        new_bill = cursor.fetchone()
        log_audit(session['user_id'], session['username'], 'UPDATE', 'bills', 
                  bill_id, old_values=old_bill, new_values=new_bill)
        
        cursor.close()
        db.close()
        return redirect(url_for('ap.ap'))
    
    cursor.execute("""
        SELECT b.*, s.name as supplier_name 
        FROM bills b
        JOIN suppliers s ON b.supplier_id = s.id
        WHERE b.id = %s AND b.user_id = %s AND b.deleted_at IS NULL
    """, (bill_id, session['user_id']))
    bill = cursor.fetchone()
    
    if not bill:
        cursor.close()
        db.close()
        return redirect(url_for('ap.ap'))
    
    business_id = session.get('business_id', session['user_id'])
    cursor.execute("""
        SELECT s.id, s.name FROM suppliers s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.deleted_at IS NULL
    """, (business_id,))
    suppliers = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('edit_bill.html',
                         username=session['username'],
                         bill=bill,
                         suppliers=suppliers)

@ap_bp.route('/add_supplier', methods=['POST'])
def add_supplier():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    name = request.form['name']
    email = request.form.get('email', '')
    phone = request.form.get('phone', '')
    address = request.form.get('address', '')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO suppliers (user_id, name, email, phone, address)
        VALUES (%s, %s, %s, %s, %s)
    """, (session['user_id'], name, email, phone, address))
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Supplier "{name}" added!', 'success')
    return redirect(url_for('ap.ap'))

@ap_bp.route('/add_bill', methods=['POST'])
def add_bill():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    supplier_id = request.form['supplier_id']
    amount = float(request.form['amount'])
    due_date = request.form['due_date']
    description = request.form.get('description', '')
    bill_number = request.form.get('bill_number', f"BILL-{supplier_id}-{due_date}")
    
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        INSERT INTO bills (user_id, supplier_id, bill_number, amount, description, due_date)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (session['user_id'], supplier_id, bill_number, amount, description, due_date))
    db.commit()
    
    if session.get('plan') in ['pro', 'enterprise']:
        cursor2 = db.cursor(dictionary=True)
        cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '2000'")
        ap_account = cursor2.fetchone()
        cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '5300'")
        expense_account = cursor2.fetchone()
        if ap_account and expense_account:
            from routes.cash import create_journal_entry
            lines = [
                {'account_id': expense_account['id'], 'debit': amount, 'credit': 0},
                {'account_id': ap_account['id'], 'debit': 0, 'credit': amount}
            ]
            create_journal_entry(
                user_id=session['user_id'],
                entry_date=due_date,
                description=f"Bill #{bill_number} - {description or 'Supplier purchase'}",
                lines=lines
            )
        cursor2.close()
    
    cursor.close()
    db.close()
    
    flash(f'Bill #{bill_number} created!', 'success')
    return redirect(url_for('ap.ap'))

@ap_bp.route('/record_bill_payment/<int:bill_id>', methods=['POST'])
def record_bill_payment(bill_id):
    """Record a payment (full or partial) against a bill"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    amount = float(request.form['amount'])
    payment_date = request.form.get('payment_date', date.today())
    payment_method = request.form.get('payment_method', 'cash')
    reference_number = request.form.get('reference_number', '')
    notes = request.form.get('notes', '')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT b.*, s.name as supplier_name 
        FROM bills b
        JOIN suppliers s ON b.supplier_id = s.id
        WHERE b.id = %s AND b.user_id = %s AND b.deleted_at IS NULL
    """, (bill_id, session['user_id']))
    bill = cursor.fetchone()
    
    if not bill:
        cursor.close()
        db.close()
        flash('Bill not found', 'error')
        return redirect(url_for('ap.ap'))
    
    # Calculate total already paid
    cursor.execute("SELECT COALESCE(SUM(amount), 0) as total_paid FROM payments WHERE bill_id = %s", (bill_id,))
    total_paid = float(cursor.fetchone()['total_paid'])
    remaining = float(bill['amount']) - total_paid
    
    if amount > remaining:
        amount = remaining
    
    if amount <= 0:
        cursor.close()
        db.close()
        flash('No remaining balance on this bill', 'error')
        return redirect(url_for('ap.ap'))
    
    # Insert payment
    cursor.execute("""
        INSERT INTO payments (user_id, bill_id, amount, payment_date, payment_method, reference_number, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (session['user_id'], bill_id, amount, payment_date, payment_method, reference_number, notes))
    
    # Create cash transaction (expense)
    cursor.execute("""
        INSERT INTO transactions (user_id, description, amount, type, category, transaction_date)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        session['user_id'],
        f"Payment to {bill['supplier_name']} - {bill['bill_number'] or 'BILL-'+str(bill_id)} ({payment_method})",
        amount,
        'expense',
        'Accounts Payable',
        payment_date
    ))
    
    # Journal entry for Pro users
    if session.get('plan') in ['pro', 'enterprise']:
        cursor2 = db.cursor(dictionary=True)
        cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '1000'")
        cash_account = cursor2.fetchone()
        cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '2000'")
        ap_account = cursor2.fetchone()
        if cash_account and ap_account:
            from routes.cash import create_journal_entry
            lines = [
                {'account_id': ap_account['id'], 'debit': amount, 'credit': 0},
                {'account_id': cash_account['id'], 'debit': 0, 'credit': amount}
            ]
            create_journal_entry(
                user_id=session['user_id'],
                entry_date=payment_date,
                description=f"Payment for {bill['bill_number'] or 'BILL-'+str(bill_id)} ({payment_method})",
                lines=lines
            )
        cursor2.close()
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Payment of ₱{amount:,.2f} recorded!', 'success')
    return redirect(url_for('ap.ap'))

@ap_bp.route('/bill_payments/<int:bill_id>')
def bill_payments(bill_id):
    """Get payment history for a bill (JSON)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT p.* FROM payments p
        WHERE p.bill_id = %s AND p.user_id = %s
        ORDER BY p.payment_date DESC
    """, (bill_id, session['user_id']))
    payments = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    for p in payments:
        if 'payment_date' in p and hasattr(p['payment_date'], 'isoformat'):
            p['payment_date'] = p['payment_date'].isoformat()
    
    return jsonify({'payments': payments})