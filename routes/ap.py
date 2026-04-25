from flask import Blueprint, render_template, request, session, redirect, url_for
from datetime import date
from models.database import get_db
from models.audit import log_audit

ap_bp = Blueprint('ap', __name__)

@ap_bp.route('/ap')
def ap():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get all suppliers (excluding soft-deleted)
    cursor.execute("SELECT * FROM suppliers WHERE user_id = %s AND deleted_at IS NULL", (session['user_id'],))
    suppliers = cursor.fetchall()
    
    # Get all bills with supplier names (excluding soft-deleted)
    cursor.execute("""
        SELECT b.*, s.name as supplier_name 
        FROM bills b
        JOIN suppliers s ON b.supplier_id = s.id
        WHERE b.user_id = %s AND b.deleted_at IS NULL
        ORDER BY b.due_date ASC
    """, (session['user_id'],))
    bills = cursor.fetchall()
    
    # Calculate total outstanding (unpaid, not deleted)
    cursor.execute("""
        SELECT SUM(amount) as total FROM bills 
        WHERE user_id = %s AND status = 'unpaid' AND deleted_at IS NULL
    """, (session['user_id'],))
    total_outstanding = cursor.fetchone()['total'] or 0
    
    cursor.close()
    db.close()
    
    return render_template('ap.html',
                         username=session['username'],
                         suppliers=suppliers,
                         bills=bills,
                         total_outstanding=total_outstanding)

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
        status = request.form['status']
        
        cursor.execute("""
            UPDATE bills 
            SET supplier_id = %s, amount = %s, due_date = %s, description = %s, status = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (supplier_id, amount, due_date, description, status, bill_id, session['user_id']))
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
    
    cursor.execute("SELECT id, name FROM suppliers WHERE user_id = %s AND deleted_at IS NULL", (session['user_id'],))
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
    cursor.close()
    db.close()
    
    return redirect(url_for('ap.ap'))

@ap_bp.route('/pay_bill/<int:bill_id>')
def pay_bill(bill_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT b.*, s.name as supplier_name 
        FROM bills b
        JOIN suppliers s ON b.supplier_id = s.id
        WHERE b.id = %s AND b.user_id = %s
    """, (bill_id, session['user_id']))
    bill = cursor.fetchone()
    
    if bill and bill['status'] == 'unpaid':
        cursor.execute("""
            UPDATE bills SET status = 'paid' 
            WHERE id = %s AND user_id = %s
        """, (bill_id, session['user_id']))
        
        cursor.execute("""
            INSERT INTO transactions (user_id, description, amount, type, category, transaction_date)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            session['user_id'],
            f"Payment to {bill['supplier_name']} - {bill['description'] or 'Bill #' + str(bill['id'])}",
            bill['amount'],
            'expense',
            'Supplies',
            date.today()
        ))
        
        db.commit()
    
    cursor.close()
    db.close()
    
    return redirect(url_for('ap.ap'))