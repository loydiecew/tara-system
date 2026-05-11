from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date
from models.database import get_db
from models.audit import log_audit

cash_bp = Blueprint('cash', __name__)

# ========== DOUBLE-ENTRY HELPER FUNCTIONS ==========
def get_account_mapping(trans_type, category, cursor):
    """Get debit/credit accounts for a transaction type and category"""
    cursor.execute("""
        SELECT debit_account_id, credit_account_id FROM transaction_account_mapping
        WHERE transaction_type = %s AND (category = %s OR category IS NULL)
        ORDER BY category IS NULL LIMIT 1
    """, (trans_type, category))
    return cursor.fetchone()

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
    
    # Get projects for dropdown
    projects = []
    if session.get('plan') in ['professional', 'suite']:
        cursor.execute("""
            SELECT p.id, p.name FROM projects p
            JOIN users u ON p.user_id = u.id
            WHERE p.deleted_at IS NULL AND u.business_id = %s AND p.status = 'active'
        """, (business_id,))
        projects = cursor.fetchall()

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
                         expense_categories=expense_categories,
                         projects=projects)
@cash_bp.route('/add_transaction', methods=['POST'])
def add_transaction():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    description = request.form['description']
    amount = float(request.form['amount'])
    trans_type = request.form['type']
    category = request.form.get('category', '')
    transaction_date = request.form.get('transaction_date', date.today())
    reference_number = request.form.get('reference_number', '')
    payment_method = request.form.get('payment_method', 'cash')
    project_id = request.form.get('project_id') or None

    # CHECK: Cashiers cannot add expenses
    if session.get('role') == 'cashier' and trans_type == 'expense':
        flash("Cashiers cannot add expenses. Only owners and admins can.", 'error')
        return redirect(url_for('cash.cash'))
    
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        INSERT INTO transactions (user_id, description, amount, type, category, transaction_date, reference_number, payment_method, project_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (session['user_id'], description, amount, trans_type, category, transaction_date, reference_number, payment_method, project_id))
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
    
    # ========== DOUBLE-ENTRY JOURNAL (Pro and Enterprise only) ==========
    if session.get('plan') in ['professional', 'suite']:
        # Get account mapping for this transaction type and category
        cursor.execute("""
            SELECT debit_account_id, credit_account_id FROM transaction_account_mapping
            WHERE transaction_type = %s AND (category = %s OR category IS NULL)
            ORDER BY category IS NULL LIMIT 1
        """, (trans_type, category))
        mapping = cursor.fetchone()
        
        if mapping:
            # Create journal entry header
            cursor.execute("""
                INSERT INTO journal_entries (user_id, entry_date, description, reference)
                VALUES (%s, %s, %s, %s)
            """, (session['user_id'], transaction_date, description, f"TRX-{cursor.lastrowid}"))
            journal_entry_id = cursor.lastrowid
            
            if trans_type == 'income':
                # Income: Debit Cash (Asset), Credit Revenue Account
                # Debit increases asset (Cash comes in)
                # Credit increases revenue
                cursor.execute("""
                    INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
                    VALUES (%s, %s, %s, %s)
                """, (journal_entry_id, mapping[0], amount, 0))
                cursor.execute("""
                    INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
                    VALUES (%s, %s, %s, %s)
                """, (journal_entry_id, mapping[1], 0, amount))
            else:
                # Expense: Debit Expense Account, Credit Cash (Asset)
                # Debit increases expense
                # Credit decreases asset (Cash goes out)
                cursor.execute("""
                    INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
                    VALUES (%s, %s, %s, %s)
                """, (journal_entry_id, mapping[0], amount, 0))
                cursor.execute("""
                    INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
                    VALUES (%s, %s, %s, %s)
                """, (journal_entry_id, mapping[1], 0, amount))
            
            db.commit()
    
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

@cash_bp.route('/receipt/cash/<int:transaction_id>')
def receipt_cash(transaction_id):
    """Generate a receipt for a cash income transaction"""
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT business_name, business_id, tin, address, phone FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get the transaction
    cursor.execute("""
        SELECT t.* FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE t.id = %s AND u.business_id = %s AND t.type = 'income' AND t.deleted_at IS NULL
    """, (transaction_id, business_id))
    transaction = cursor.fetchone()
    
    if not transaction:
        cursor.close()
        db.close()
        flash('Transaction not found or is not an income transaction', 'error')
        return redirect(url_for('cash.cash'))
    
    # Get business owner details (including VAT)
    cursor.execute("""
        SELECT username, business_name, business_id, vat_registered FROM users
        WHERE business_id = %s AND role IN ('admin', 'owner')
        LIMIT 1
    """, (business_id,))
    owner = cursor.fetchone()
    
    cursor.close()
    db.close()
    
    business_name = owner['business_name'] if owner and owner.get('business_name') else 'My Business'
    business_id_num = owner['business_id'] if owner and owner.get('business_id') else business_id
    vat_registered = bool(owner['vat_registered']) if owner else False
    
    receipt_number = f"RCPT-{transaction_id:06d}"
    today = date.today()
    
    # Determine who paid — extract name from description if possible
    customer_name = transaction['description']
    if ' from ' in customer_name.lower():
        parts = customer_name.split(' from ', 1)
        customer_name = parts[1] if len(parts) > 1 else customer_name
    elif 'received from' in customer_name.lower():
        parts = customer_name.lower().split('received from', 1)
        customer_name = parts[1].strip() if len(parts) > 1 else customer_name
    
    return render_template('receipt.html', user=user,
                         receipt_number=receipt_number,
                         receipt_title='Cash Receipt',
                         receipt_date=str(transaction['transaction_date']),
                         business_name=business_name,
                         business_id=business_id_num,
                         customer_label='Received From',
                         customer_name=customer_name,
                         description=transaction['description'],
                         amount=float(transaction['amount']),
                         payment_method='Cash',
                         reference_number='',
                         invoice_number='',
                         today=today,
                         back_url='cash',
                         username=session['username'],
                         vat_registered=vat_registered)

def create_journal_entry(user_id, entry_date, description, lines):
    """Create a journal entry with debit/credit lines"""
    db = get_db()
    cursor = db.cursor()
    
    # Create journal entry header
    cursor.execute("""
        INSERT INTO journal_entries (user_id, entry_date, description)
        VALUES (%s, %s, %s)
    """, (user_id, entry_date, description))
    entry_id = cursor.lastrowid
    
    # Create journal lines
    for line in lines:
        cursor.execute("""
            INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
            VALUES (%s, %s, %s, %s)
        """, (entry_id, line['account_id'], line.get('debit', 0), line.get('credit', 0)))
    
    db.commit()
    cursor.close()
    db.close()
    return entry_id
