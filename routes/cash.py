from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date
from models.database import get_db
from models.audit import log_audit

cash_bp = Blueprint('cash', __name__)

@cash_bp.route('/cash')
def cash():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get user's industry for categories
    cursor.execute("SELECT industry FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    industry = user['industry'] if user else 'retail'
    
    # Get categories
    cursor.execute("""
        SELECT name, type FROM categories 
        WHERE (user_id IS NULL OR user_id = %s) 
        AND (industry IS NULL OR industry = %s OR industry = 'all')
        ORDER BY 
            CASE WHEN type = 'income' THEN 1 ELSE 2 END,
            name
    """, (session['user_id'], industry))
    categories = cursor.fetchall()
    
    income_categories = [c for c in categories if c['type'] == 'income']
    expense_categories = [c for c in categories if c['type'] == 'expense']
    
    # Get transactions for this business
    cursor.execute("""
        SELECT t.* FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.deleted_at IS NULL
        ORDER BY t.transaction_date DESC
    """, (business_id,))
    transactions = cursor.fetchall()
    
    # Calculate totals
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN t.type = 'income' THEN t.amount ELSE 0 END) as total_income,
            SUM(CASE WHEN t.type = 'expense' THEN t.amount ELSE 0 END) as total_expense
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.deleted_at IS NULL
    """, (business_id,))
    totals = cursor.fetchone()
    
    total_income = float(totals['total_income']) if totals['total_income'] is not None else 0.0
    total_expense = float(totals['total_expense']) if totals['total_expense'] is not None else 0.0
    balance = total_income - total_expense
    
    cursor.close()
    db.close()
    
    today = date.today().isoformat()
    
    return render_template('cash.html',
                         username=session['username'],
                         transactions=transactions,
                         total_income=total_income,
                         total_expense=total_expense,
                         balance=balance,
                         today=today,
                         income_categories=income_categories,
                         expense_categories=expense_categories)

@cash_bp.route('/add_transaction', methods=['POST'])
def add_transaction():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    description = request.form['description']
    amount = float(request.form['amount'])
    trans_type = request.form['type']
    category = request.form.get('category', '')
    transaction_date = request.form.get('transaction_date', date.today())
    
    # CHECK: Cashiers cannot add expenses
    if session.get('role') == 'cashier' and trans_type == 'expense':
        flash("Cashiers cannot add expenses. Only owners and admins can.", 'error')
        return redirect(url_for('cash.cash'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO transactions (user_id, description, amount, type, category, transaction_date)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (session['user_id'], description, amount, trans_type, category, transaction_date))
    db.commit()

    new_transaction = {
        'id': cursor.lastrowid,
        'description': description,
        'amount': amount,
        'type': trans_type,
        'category': category,
        'transaction_date': str(transaction_date)
    }
    log_audit(session['user_id'], session['username'], 'CREATE', 'transactions', 
            cursor.lastrowid, new_values=new_transaction)

    cursor.close()
    db.close()
    
    return redirect(url_for('cash.cash'))

@cash_bp.route('/delete_transaction/<int:transaction_id>')
def delete_transaction(transaction_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM transactions WHERE id = %s AND user_id = %s", 
                   (transaction_id, session['user_id']))
    transaction = cursor.fetchone()
    
    if transaction and transaction.get('deleted_at') is None:
        cursor.execute("""
            UPDATE transactions SET deleted_at = NOW() 
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (transaction_id, session['user_id']))
        db.commit()
        
        log_audit(session['user_id'], session['username'], 'DELETE', 'transactions', 
                  transaction_id, old_values=transaction)
    
    cursor.close()
    db.close()
    
    return redirect(url_for('cash.cash'))

@cash_bp.route('/edit_transaction/<int:transaction_id>', methods=['GET', 'POST'])
def edit_transaction(transaction_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("SELECT * FROM transactions WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                       (transaction_id, session['user_id']))
        old_transaction = cursor.fetchone()
        
        if not old_transaction:
            cursor.close()
            db.close()
            return redirect(url_for('cash.cash'))
        
        description = request.form['description']
        amount = float(request.form['amount'])
        trans_type = request.form['type']
        category = request.form.get('category', '')
        transaction_date = request.form.get('transaction_date')
        
        cursor.execute("""
            UPDATE transactions 
            SET description = %s, amount = %s, type = %s, category = %s, transaction_date = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (description, amount, trans_type, category, transaction_date, transaction_id, session['user_id']))
        db.commit()
        
        cursor.execute("SELECT * FROM transactions WHERE id = %s", (transaction_id,))
        new_transaction = cursor.fetchone()
        
        log_audit(session['user_id'], session['username'], 'UPDATE', 'transactions', 
                  transaction_id, old_values=old_transaction, new_values=new_transaction)
        
        cursor.close()
        db.close()
        return redirect(url_for('cash.cash'))
    
    cursor.execute("SELECT * FROM transactions WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                   (transaction_id, session['user_id']))
    transaction = cursor.fetchone()
    
    if not transaction:
        cursor.close()
        db.close()
        return redirect(url_for('cash.cash'))
    
    cursor.close()
    db.close()
    
    today = date.today().isoformat()
    
    return render_template('edit_transaction.html',
                         username=session['username'],
                         transaction=transaction,
                         today=today)