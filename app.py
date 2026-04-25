from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import mysql.connector
import hashlib
from datetime import date, timedelta

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True   # ADD THIS LINE
app.secret_key = 'tara-secret-key'

@app.context_processor
def inject_plan():
    """Make plan and feature checks available in all templates"""
    if 'user_id' in session:
        return {
            'user_plan': session.get('plan', 'basic'),
            'user_plan_name': session.get('plan_name', 'Basic'),
            'has_feature': lambda feature: user_has_feature(session['user_id'], feature)
        }
    return {
        'user_plan': 'basic',
        'user_plan_name': 'Basic',
        'has_feature': lambda feature: False
    }

def get_db():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='georgeorwell#1984',  
        database='tara_system'
    )

# ========== TIER / PLAN HELPERS ==========
def get_user_plan(user_id):
    """Get user's current plan"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.id, p.name, p.slug, p.price_monthly, p.max_users 
        FROM users u
        JOIN plans p ON u.plan_id = p.id
        WHERE u.id = %s
    """, (user_id,))
    plan = cursor.fetchone()
    cursor.close()
    db.close()
    return plan

def user_has_feature(user_id, feature_name):
    """Check if user's plan includes a specific feature"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT COUNT(*) as has_feature
        FROM users u
        JOIN plans p ON u.plan_id = p.id
        JOIN plan_features pf ON p.id = pf.plan_id
        JOIN features f ON pf.feature_id = f.id
        WHERE u.id = %s AND f.name = %s
    """, (user_id, feature_name))
    result = cursor.fetchone()
    cursor.close()
    db.close()
    return result['has_feature'] > 0

def get_user_features(user_id):
    """Get list of features available to user"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT f.name
        FROM users u
        JOIN plans p ON u.plan_id = p.id
        JOIN plan_features pf ON p.id = pf.plan_id
        JOIN features f ON pf.feature_id = f.id
        WHERE u.id = %s
    """, (user_id,))
    features = [row['name'] for row in cursor.fetchall()]
    cursor.close()
    db.close()
    return features

def require_feature(feature_name):
    """Decorator to check if user has access to a feature"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if not user_has_feature(session['user_id'], feature_name):
                return render_template('errors/upgrade_required.html', 
                                     feature_name=feature_name.replace('_', ' ').title()), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/plan')
def plan():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get all plans
    cursor.execute("SELECT * FROM plans ORDER BY price_monthly ASC")
    all_plans = cursor.fetchall()
    
    # Get current user's plan
    current_plan = get_user_plan(session['user_id'])
    
    cursor.close()
    db.close()
    
    return render_template('plan.html',
                         username=session['username'],
                         plans=all_plans,
                         current_plan=current_plan)

# ========== AUDIT LOG & SOFT DELETE HELPERS ==========
import json
from functools import wraps

# ========== AUDIT LOG HELPER ==========
def log_audit(user_id, username, action, table_name, record_id, old_values=None, new_values=None, ip_address=None):
    """Log all changes to audit_log table"""
    db = get_db()
    cursor = db.cursor()
    
    # Get IP address if not provided
    if ip_address is None and hasattr(request, 'remote_addr'):
        ip_address = request.remote_addr
    
    # Convert old_values and new_values to JSON string
    old_json = json.dumps(old_values, default=str) if old_values else None
    new_json = json.dumps(new_values, default=str) if new_values else None
    
    cursor.execute("""
        INSERT INTO audit_log (user_id, username, action, table_name, record_id, old_values, new_values, ip_address)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (user_id, username, action, table_name, record_id, old_json, new_json, ip_address))
    db.commit()
    cursor.close()
    db.close()

# ========== DECORATOR FOR ROUTE LOGGING (Optional) ==========
def audit_action(table_name, get_record_id=None):
    """Decorator to automatically log actions"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get old record before change (if editing)
            # This is complex; we'll do manual logging instead
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def soft_delete(table_name, record_id, user_id, username):
    """Generic soft delete function"""
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        # First, get the record before deleting (for audit log)
        cursor.execute(f"SELECT * FROM {table_name} WHERE id = %s", (record_id,))
        old_record = cursor.fetchone()
        
        if old_record:
            # Soft delete
            cursor.execute(f"UPDATE {table_name} SET deleted_at = NOW() WHERE id = %s AND deleted_at IS NULL", (record_id,))
            db.commit()
            
            # Log to audit
            log_audit(user_id, username, 'DELETE', table_name, record_id, old_values=old_record)
            
            cursor.close()
            db.close()
            return True
        
        cursor.close()
        db.close()
        return False
    except Exception as e:
        print(f"Soft delete error: {e}")
        return False

def restore_record(table_name, record_id, user_id, username):
    """Restore a soft-deleted record"""
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        # Get the deleted record
        cursor.execute(f"SELECT * FROM {table_name} WHERE id = %s AND deleted_at IS NOT NULL", (record_id,))
        old_record = cursor.fetchone()
        
        if old_record:
            # Restore (set deleted_at to NULL)
            cursor.execute(f"UPDATE {table_name} SET deleted_at = NULL WHERE id = %s", (record_id,))
            db.commit()
            
            # Log to audit
            log_audit(user_id, username, 'RESTORE', table_name, record_id, old_values=old_record)
            
            cursor.close()
            db.close()
            return True
        
        cursor.close()
        db.close()
        return False
    except Exception as e:
        print(f"Restore error: {e}")
        return False

# ========== CATEGORY HELPERS ==========
def get_categories(user_id, trans_type, industry=None):
    """Get categories for dropdown based on user's industry"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if industry is None:
        # Get user's industry
        cursor.execute("SELECT industry FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        industry = user['industry'] if user else 'retail'
    
    # Get categories: system defaults + user's custom categories
    cursor.execute("""
        SELECT id, name FROM categories 
        WHERE (user_id IS NULL OR user_id = %s) 
        AND type = %s 
        AND (industry IS NULL OR industry = %s OR industry = 'all')
        ORDER BY name
    """, (user_id, trans_type, industry))
    
    categories = cursor.fetchall()
    cursor.close()
    db.close()
    return categories

def add_custom_category(user_id, name, trans_type, industry):
    """Add a user-created category"""
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        INSERT INTO categories (user_id, name, type, industry, is_custom)
        VALUES (%s, %s, %s, %s, TRUE)
        ON DUPLICATE KEY UPDATE id=id
    """, (user_id, name, trans_type, industry))
    db.commit()
    
    cursor.close()
    db.close()

@app.route('/api/categories')
def api_categories():
    """AJAX endpoint to get categories by type"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    trans_type = request.args.get('type', 'income')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get user's industry
    cursor.execute("SELECT industry FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    industry = user['industry'] if user else 'retail'
    
    # Get categories
    cursor.execute("""
        SELECT name, type FROM categories 
        WHERE (user_id IS NULL OR user_id = %s) 
        AND type = %s
        AND (industry IS NULL OR industry = %s OR industry = 'all')
        ORDER BY name
    """, (session['user_id'], trans_type, industry))
    
    categories = cursor.fetchall()
    cursor.close()
    db.close()
    
    result = {trans_type: categories}
    return jsonify(result)

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        # Check user credentials
        cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
        user = cursor.fetchone()
        
        if user:
            # Store basic user info in session
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            
            # Get user's plan (using the same cursor, before closing)
            plan_id = user.get('plan_id', 1)
            cursor.execute("SELECT slug, name FROM plans WHERE id = %s", (plan_id,))
            plan = cursor.fetchone()
            
            session['plan'] = plan['slug'] if plan else 'basic'
            session['plan_name'] = plan['name'] if plan else 'Basic'
            
            cursor.close()
            db.close()
            return redirect(url_for('dashboard'))
        
        cursor.close()
        db.close()
        return render_template('login.html', error='Invalid credentials')
    
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get current month's date range
    today = date.today()
    first_day = today.replace(day=1)
    
    # Get last day of month
    if today.month == 12:
        last_day = today.replace(day=31)
    else:
        next_month = today.replace(month=today.month + 1, day=1)
        last_day = next_month - timedelta(days=1)
    
    # Get last month's date range
    if today.month == 1:
        last_month_first = today.replace(year=today.year - 1, month=12, day=1)
    else:
        last_month_first = today.replace(month=today.month - 1, day=1)
    
    if last_month_first.month == 12:
        last_month_last = last_month_first.replace(day=31)
    else:
        next_month_last = last_month_first.replace(month=last_month_first.month + 1, day=1)
        last_month_last = next_month_last - timedelta(days=1)
    
    # ========== CORE FINANCIAL ==========
    # Monthly income
    cursor.execute("""
        SELECT SUM(amount) as total FROM transactions 
        WHERE user_id = %s AND type = 'income' 
        AND transaction_date BETWEEN %s AND %s
    """, (session['user_id'], first_day, last_day))
    monthly_income = float(cursor.fetchone()['total'] or 0)
    
    # Monthly expense
    cursor.execute("""
        SELECT SUM(amount) as total FROM transactions 
        WHERE user_id = %s AND type = 'expense' 
        AND transaction_date BETWEEN %s AND %s
    """, (session['user_id'], first_day, last_day))
    monthly_expense = float(cursor.fetchone()['total'] or 0)
    
    # Monthly profit
    current_profit = monthly_income - monthly_expense
    
    # Last month income
    cursor.execute("""
        SELECT SUM(amount) as total FROM transactions 
        WHERE user_id = %s AND type = 'income' 
        AND transaction_date BETWEEN %s AND %s
    """, (session['user_id'], last_month_first, last_month_last))
    last_monthly_income = float(cursor.fetchone()['total'] or 0)
    
    # Last month expense
    cursor.execute("""
        SELECT SUM(amount) as total FROM transactions 
        WHERE user_id = %s AND type = 'expense' 
        AND transaction_date BETWEEN %s AND %s
    """, (session['user_id'], last_month_first, last_month_last))
    last_monthly_expense = float(cursor.fetchone()['total'] or 0)
    
    last_profit = last_monthly_income - last_monthly_expense
    
    # Calculate changes
    def calc_change(current, last):
        if last == 0:
            return 0.0 if current == 0 else 100.0
        return ((current - last) / last) * 100.0
    
    sales_change = calc_change(monthly_income, last_monthly_income)
    expense_change = calc_change(monthly_expense, last_monthly_expense)
    profit_change = calc_change(current_profit, last_profit)
    profit_margin = (current_profit / monthly_income * 100) if monthly_income > 0 else 0
    
    # ========== CASH BALANCE (all time) ==========
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) as total_income,
            SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) as total_expense
        FROM transactions WHERE user_id = %s
    """, (session['user_id'],))
    totals = cursor.fetchone()
    cash_balance = (float(totals['total_income'] or 0)) - (float(totals['total_expense'] or 0))
    
    # ========== AR OUTSTANDING ==========
    cursor.execute("""
        SELECT SUM(amount) as total FROM invoices 
        WHERE user_id = %s AND status = 'unpaid'
    """, (session['user_id'],))
    ar_outstanding = float(cursor.fetchone()['total'] or 0)
    
    # ========== AP OUTSTANDING ==========
    cursor.execute("""
        SELECT SUM(amount) as total FROM bills 
        WHERE user_id = %s AND status = 'unpaid'
    """, (session['user_id'],))
    ap_outstanding = float(cursor.fetchone()['total'] or 0)
    
    # ========== INVENTORY SUMMARY ==========
    cursor.execute("""
        SELECT 
            SUM(quantity * price) as total_value,
            COUNT(*) as total_products,
            SUM(CASE WHEN quantity < reorder_level THEN 1 ELSE 0 END) as low_stock_count
        FROM products WHERE user_id = %s
    """, (session['user_id'],))
    inv_summary = cursor.fetchone()
    inventory_value = float(inv_summary['total_value'] or 0)
    total_products = inv_summary['total_products'] or 0
    low_stock_count = inv_summary['low_stock_count'] or 0
    
    # ========== RECENT TRANSACTIONS ==========
    cursor.execute("""
        SELECT * FROM transactions 
        WHERE user_id = %s 
        ORDER BY transaction_date DESC 
        LIMIT 10
    """, (session['user_id'],))
    recent = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('dashboard.html',
                         username=session['username'],
                         monthly_income=monthly_income,
                         monthly_expense=monthly_expense,
                         profit=current_profit,
                         sales_change=sales_change,
                         expense_change=expense_change,
                         profit_change=profit_change,
                         profit_margin=profit_margin,
                         cash_balance=cash_balance,
                         ar_outstanding=ar_outstanding,
                         ap_outstanding=ap_outstanding,
                         inventory_value=inventory_value,
                         total_products=total_products,
                         low_stock_count=low_stock_count,
                         transactions=recent)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ========== CASH MODULE ==========
@app.route('/cash')
def cash():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get user's industry
    cursor.execute("SELECT industry FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    industry = user['industry'] if user else 'retail'
    
    # Get categories from database (no AJAX, just direct query)
    cursor.execute("""
        SELECT name, type FROM categories 
        WHERE (user_id IS NULL OR user_id = %s) 
        AND (industry IS NULL OR industry = %s OR industry = 'all')
        ORDER BY 
            CASE WHEN type = 'income' THEN 1 ELSE 2 END,
            name
    """, (session['user_id'], industry))
    categories = cursor.fetchall()
    
    # Separate income and expense categories
    income_categories = [c for c in categories if c['type'] == 'income']
    expense_categories = [c for c in categories if c['type'] == 'expense']
    
    # Get transactions
    cursor.execute("""
        SELECT * FROM transactions 
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY transaction_date DESC
    """, (session['user_id'],))
    transactions = cursor.fetchall()
    
    # Calculate totals
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) as total_income,
            SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) as total_expense
        FROM transactions 
        WHERE user_id = %s AND deleted_at IS NULL
    """, (session['user_id'],))
    totals = cursor.fetchone()
    
    total_income = float(totals['total_income']) if totals['total_income'] is not None else 0.0
    total_expense = float(totals['total_expense']) if totals['total_expense'] is not None else 0.0
    balance = total_income - total_expense
    
    cursor.close()
    db.close()
    
    from datetime import date
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

@app.route('/add_transaction', methods=['POST'])
def add_transaction():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    description = request.form['description']
    amount = float(request.form['amount'])
    trans_type = request.form['type']
    category = request.form.get('category', '')
    transaction_date = request.form.get('transaction_date', date.today())
    
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
    
    return redirect(url_for('cash'))

@app.route('/delete_transaction/<int:transaction_id>')
def delete_transaction(transaction_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get transaction before deletion (for audit)
    cursor.execute("SELECT * FROM transactions WHERE id = %s AND user_id = %s", 
                   (transaction_id, session['user_id']))
    transaction = cursor.fetchone()
    
    if transaction and transaction.get('deleted_at') is None:
        # Soft delete
        cursor.execute("""
            UPDATE transactions SET deleted_at = NOW() 
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (transaction_id, session['user_id']))
        db.commit()
        
        # Log to audit - DELETE
        log_audit(session['user_id'], session['username'], 'DELETE', 'transactions', 
                  transaction_id, old_values=transaction)
    
    cursor.close()
    db.close()
    
    return redirect(url_for('cash'))

@app.route('/edit_transaction/<int:transaction_id>', methods=['GET', 'POST'])
def edit_transaction(transaction_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        # Get old values first (for audit)
        cursor.execute("SELECT * FROM transactions WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                       (transaction_id, session['user_id']))
        old_transaction = cursor.fetchone()
        
        if not old_transaction:
            cursor.close()
            db.close()
            return redirect(url_for('cash'))
        
        # Get new values from form
        description = request.form['description']
        amount = float(request.form['amount'])
        trans_type = request.form['type']
        category = request.form.get('category', '')
        transaction_date = request.form.get('transaction_date')
        
        # Update transaction
        cursor.execute("""
            UPDATE transactions 
            SET description = %s, amount = %s, type = %s, category = %s, transaction_date = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (description, amount, trans_type, category, transaction_date, transaction_id, session['user_id']))
        db.commit()
        
        # Get new values after update
        cursor.execute("SELECT * FROM transactions WHERE id = %s", (transaction_id,))
        new_transaction = cursor.fetchone()
        
        # Log to audit - UPDATE
        log_audit(session['user_id'], session['username'], 'UPDATE', 'transactions', 
                  transaction_id, old_values=old_transaction, new_values=new_transaction)
        
        cursor.close()
        db.close()
        return redirect(url_for('cash'))
    
    # GET request - show edit form
    cursor.execute("SELECT * FROM transactions WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                   (transaction_id, session['user_id']))
    transaction = cursor.fetchone()
    
    if not transaction:
        cursor.close()
        db.close()
        return redirect(url_for('cash'))
    
    cursor.close()
    db.close()
    
    from datetime import date
    today = date.today().isoformat()
    
    return render_template('edit_transaction.html',
                         username=session['username'],
                         transaction=transaction,
                         today=today)

# ========== SALES MODULE ==========
@app.route('/sales')
def sales():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get all sales (excluding soft-deleted)
    cursor.execute("""
        SELECT * FROM sales 
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY sale_date DESC
    """, (session['user_id'],))
    sales_list = cursor.fetchall()
    
    # Get total sales (all time, excluding soft-deleted)
    cursor.execute("""
        SELECT SUM(amount) as total FROM sales 
        WHERE user_id = %s AND deleted_at IS NULL
    """, (session['user_id'],))
    total_result = cursor.fetchone()
    total_sales = float(total_result['total']) if total_result['total'] is not None else 0.0
    
    # Get this month's sales (excluding soft-deleted)
    from datetime import date
    today = date.today()
    first_day = today.replace(day=1)
    
    cursor.execute("""
        SELECT SUM(amount) as total FROM sales 
        WHERE user_id = %s AND deleted_at IS NULL
        AND sale_date BETWEEN %s AND %s
    """, (session['user_id'], first_day, today))
    monthly_result = cursor.fetchone()
    monthly_sales = float(monthly_result['total']) if monthly_result['total'] is not None else 0.0
    
    # Get products for dropdown (excluding soft-deleted)
    cursor.execute("""
        SELECT id, name, price, quantity FROM products 
        WHERE user_id = %s AND deleted_at IS NULL
    """, (session['user_id'],))
    products = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('sales.html',
                         username=session['username'],
                         sales=sales_list,
                         total_sales=total_sales,
                         monthly_sales=monthly_sales,
                         products=products,
                         today=today.isoformat())

@app.route('/add_sale', methods=['POST'])
def add_sale():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Check if sale is from inventory dropdown or manual entry
    product_id = request.form.get('product_id')
    
    if product_id and product_id != '':
        # Sale from inventory dropdown
        product_id = int(product_id)
        quantity = int(request.form.get('quantity', 1))
        
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        # Get product details
        cursor.execute("SELECT name, price FROM products WHERE id = %s AND user_id = %s", 
                       (product_id, session['user_id']))
        product = cursor.fetchone()
        
        if product:
            amount = product['price'] * quantity
            customer_name = request.form.get('customer_name', 'Walk-in Customer')
            description = f"{quantity}x {product['name']}"
            sale_date = request.form.get('sale_date', date.today())
            
            # Insert sale
            cursor.execute("""
                INSERT INTO sales (user_id, customer_name, amount, sale_date, description)
                VALUES (%s, %s, %s, %s, %s)
            """, (session['user_id'], customer_name, amount, sale_date, description))
            
            # Deduct from inventory
            cursor.execute("""
                UPDATE products SET quantity = quantity - %s 
                WHERE id = %s AND user_id = %s AND quantity >= %s
            """, (quantity, product_id, session['user_id'], quantity))
            
            db.commit()
        cursor.close()
        db.close()
        
    else:
        # Manual sale - FIXED: Use correct field names
        customer_name = request.form.get('customer_name_manual', request.form.get('customer_name', 'Walk-in Customer'))
        amount = float(request.form.get('amount_manual', request.form.get('amount', 0)))
        sale_date = request.form.get('sale_date', date.today())
        description = request.form.get('description_manual', request.form.get('description', ''))
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO sales (user_id, customer_name, amount, sale_date, description)
            VALUES (%s, %s, %s, %s, %s)
        """, (session['user_id'], customer_name, amount, sale_date, description))
        db.commit()
        cursor.close()
        db.close()
    
    return redirect(url_for('sales'))

@app.route('/delete_sale/<int:sale_id>')
def delete_sale(sale_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get sale before deletion (for audit)
    cursor.execute("SELECT * FROM sales WHERE id = %s AND user_id = %s", 
                   (sale_id, session['user_id']))
    sale = cursor.fetchone()
    
    if sale and sale.get('deleted_at') is None:
        # Soft delete
        cursor.execute("""
            UPDATE sales SET deleted_at = NOW() 
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (sale_id, session['user_id']))
        db.commit()
        
        # Log to audit
        log_audit(session['user_id'], session['username'], 'DELETE', 'sales', 
                  sale_id, old_values=sale)
    
    cursor.close()
    db.close()
    
    return redirect(url_for('sales'))

@app.route('/edit_sale/<int:sale_id>', methods=['GET', 'POST'])
def edit_sale(sale_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        # Get old values first (for audit)
        cursor.execute("SELECT * FROM sales WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                       (sale_id, session['user_id']))
        old_sale = cursor.fetchone()
        
        if not old_sale:
            cursor.close()
            db.close()
            return redirect(url_for('sales'))
        
        # Get new values from form
        customer_name = request.form['customer_name']
        amount = float(request.form['amount'])
        sale_date = request.form['sale_date']
        description = request.form.get('description', '')
        
        # Update sale
        cursor.execute("""
            UPDATE sales 
            SET customer_name = %s, amount = %s, sale_date = %s, description = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (customer_name, amount, sale_date, description, sale_id, session['user_id']))
        db.commit()
        
        # Get new values after update
        cursor.execute("SELECT * FROM sales WHERE id = %s", (sale_id,))
        new_sale = cursor.fetchone()
        
        # Log to audit
        log_audit(session['user_id'], session['username'], 'UPDATE', 'sales', 
                  sale_id, old_values=old_sale, new_values=new_sale)
        
        cursor.close()
        db.close()
        return redirect(url_for('sales'))
    
    # GET request - show edit form
    cursor.execute("SELECT * FROM sales WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                   (sale_id, session['user_id']))
    sale = cursor.fetchone()
    
    if not sale:
        cursor.close()
        db.close()
        return redirect(url_for('sales'))
    
    cursor.close()
    db.close()
    
    from datetime import date
    today = date.today().isoformat()
    
    return render_template('edit_sale.html',
                         username=session['username'],
                         sale=sale,
                         today=today)

# ========== GENERAL JOURNAL ==========
@app.route('/journal')
def journal():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get ALL transactions (cash + sales combined)
    # We need to UNION (combine) two tables
    
    # First, get cash transactions
    cursor.execute("""
        SELECT 
            transaction_date as date,
            description,
            category,
            type,
            amount,
            'cash' as source
        FROM transactions 
        WHERE user_id = %s
    """, (session['user_id'],))
    cash_transactions = cursor.fetchall()
    
    # Second, get sales
    cursor.execute("""
        SELECT 
            sale_date as date,
            CONCAT('Sale to ', customer_name) as description,
            'Sales' as category,
            'income' as type,
            amount,
            'sales' as source
        FROM sales 
        WHERE user_id = %s
    """, (session['user_id'],))
    sales_transactions = cursor.fetchall()
    
    # Combine both lists
    all_transactions = cash_transactions + sales_transactions
    
    # Sort by date (newest first)
    all_transactions.sort(key=lambda x: x['date'], reverse=True)
    
    # Calculate totals
    total_income = sum(t['amount'] for t in all_transactions if t['type'] == 'income')
    total_expense = sum(t['amount'] for t in all_transactions if t['type'] == 'expense')
    net = total_income - total_expense
    
    cursor.close()
    db.close()
    
    return render_template('journal.html',
                         username=session['username'],
                         transactions=all_transactions,
                         total_income=total_income,
                         total_expense=total_expense,
                         net=net)

# ========== ACCOUNTS RECEIVABLE (AR) ==========
from functools import wraps

@app.route('/ar')
#@require_feature('accounts_receivable')
def ar():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get all customers (excluding soft-deleted)
    cursor.execute("SELECT * FROM customers WHERE user_id = %s AND deleted_at IS NULL", (session['user_id'],))
    customers = cursor.fetchall()
    
    # Get all invoices with customer names (excluding soft-deleted)
    cursor.execute("""
        SELECT i.*, c.name as customer_name 
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.user_id = %s AND i.deleted_at IS NULL
        ORDER BY i.due_date ASC
    """, (session['user_id'],))
    invoices = cursor.fetchall()
    
    # Calculate total outstanding (unpaid, not deleted)
    cursor.execute("""
        SELECT SUM(amount) as total FROM invoices 
        WHERE user_id = %s AND status = 'unpaid' AND deleted_at IS NULL
    """, (session['user_id'],))
    total_outstanding = cursor.fetchone()['total'] or 0
    
    cursor.close()
    db.close()
    
    return render_template('ar.html',
                         username=session['username'],
                         customers=customers,
                         invoices=invoices,
                         total_outstanding=total_outstanding)

@app.route('/delete_invoice/<int:invoice_id>')
def delete_invoice(invoice_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get invoice before deletion (for audit)
    cursor.execute("SELECT * FROM invoices WHERE id = %s AND user_id = %s", 
                   (invoice_id, session['user_id']))
    invoice = cursor.fetchone()
    
    if invoice and invoice.get('deleted_at') is None:
        # Soft delete
        cursor.execute("""
            UPDATE invoices SET deleted_at = NOW() 
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (invoice_id, session['user_id']))
        db.commit()
        
        # Log to audit
        log_audit(session['user_id'], session['username'], 'DELETE', 'invoices', 
                  invoice_id, old_values=invoice)
    
    cursor.close()
    db.close()
    
    return redirect(url_for('ar'))

@app.route('/edit_invoice/<int:invoice_id>', methods=['GET', 'POST'])
def edit_invoice(invoice_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        # Get old values first (for audit)
        cursor.execute("SELECT * FROM invoices WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                       (invoice_id, session['user_id']))
        old_invoice = cursor.fetchone()
        
        if not old_invoice:
            cursor.close()
            db.close()
            return redirect(url_for('ar'))
        
        # Get new values from form
        customer_id = request.form['customer_id']
        amount = float(request.form['amount'])
        due_date = request.form['due_date']
        status = request.form['status']
        
        # Update invoice
        cursor.execute("""
            UPDATE invoices 
            SET customer_id = %s, amount = %s, due_date = %s, status = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (customer_id, amount, due_date, status, invoice_id, session['user_id']))
        db.commit()
        
        # Get new values after update
        cursor.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
        new_invoice = cursor.fetchone()
        
        # Log to audit
        log_audit(session['user_id'], session['username'], 'UPDATE', 'invoices', 
                  invoice_id, old_values=old_invoice, new_values=new_invoice)
        
        cursor.close()
        db.close()
        return redirect(url_for('ar'))
    
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
        return redirect(url_for('ar'))
    
    # Get customers for dropdown
    cursor.execute("SELECT id, name FROM customers WHERE user_id = %s AND deleted_at IS NULL", (session['user_id'],))
    customers = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('edit_invoice.html',
                         username=session['username'],
                         invoice=invoice,
                         customers=customers)

@app.route('/add_customer', methods=['POST'])
def add_customer():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
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
    
    return redirect(url_for('ar'))

@app.route('/add_invoice', methods=['POST'])
def add_invoice():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    customer_id = request.form['customer_id']
    amount = float(request.form['amount'])
    due_date = request.form['due_date']
    invoice_number = request.form.get('invoice_number', f"INV-{customer_id}-{due_date}")
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO invoices (user_id, customer_id, invoice_number, amount, due_date)
        VALUES (%s, %s, %s, %s, %s)
    """, (session['user_id'], customer_id, invoice_number, amount, due_date))
    db.commit()
    cursor.close()
    db.close()
    
    return redirect(url_for('ar'))

@app.route('/pay_invoice/<int:invoice_id>')
def pay_invoice(invoice_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get the invoice details
    cursor.execute("""
        SELECT i.*, c.name as customer_name 
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.id = %s AND i.user_id = %s
    """, (invoice_id, session['user_id']))
    invoice = cursor.fetchone()
    
    if invoice and invoice['status'] == 'unpaid':
        # Mark invoice as paid
        cursor.execute("""
            UPDATE invoices SET status = 'paid' 
            WHERE id = %s AND user_id = %s
        """, (invoice_id, session['user_id']))
        
        # Create a cash transaction for the payment
        from datetime import date
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
        
        db.commit()
    
    cursor.close()
    db.close()
    
    return redirect(url_for('ar'))

    # ========== ACCOUNTS PAYABLE (AP) ==========
from functools import wraps

@app.route('/ap')
#@require_feature('accounts_payable')
def ap():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
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

@app.route('/delete_bill/<int:bill_id>')
def delete_bill(bill_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get bill before deletion (for audit)
    cursor.execute("SELECT * FROM bills WHERE id = %s AND user_id = %s", 
                   (bill_id, session['user_id']))
    bill = cursor.fetchone()
    
    if bill and bill.get('deleted_at') is None:
        # Soft delete
        cursor.execute("""
            UPDATE bills SET deleted_at = NOW() 
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (bill_id, session['user_id']))
        db.commit()
        
        # Log to audit
        log_audit(session['user_id'], session['username'], 'DELETE', 'bills', 
                  bill_id, old_values=bill)
    
    cursor.close()
    db.close()
    
    return redirect(url_for('ap'))

@app.route('/edit_bill/<int:bill_id>', methods=['GET', 'POST'])
def edit_bill(bill_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        # Get old values first (for audit)
        cursor.execute("SELECT * FROM bills WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                       (bill_id, session['user_id']))
        old_bill = cursor.fetchone()
        
        if not old_bill:
            cursor.close()
            db.close()
            return redirect(url_for('ap'))
        
        # Get new values from form
        supplier_id = request.form['supplier_id']
        amount = float(request.form['amount'])
        due_date = request.form['due_date']
        description = request.form.get('description', '')
        status = request.form['status']
        
        # Update bill
        cursor.execute("""
            UPDATE bills 
            SET supplier_id = %s, amount = %s, due_date = %s, description = %s, status = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (supplier_id, amount, due_date, description, status, bill_id, session['user_id']))
        db.commit()
        
        # Get new values after update
        cursor.execute("SELECT * FROM bills WHERE id = %s", (bill_id,))
        new_bill = cursor.fetchone()
        
        # Log to audit
        log_audit(session['user_id'], session['username'], 'UPDATE', 'bills', 
                  bill_id, old_values=old_bill, new_values=new_bill)
        
        cursor.close()
        db.close()
        return redirect(url_for('ap'))
    
    # GET request - show edit form
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
        return redirect(url_for('ap'))
    
    # Get suppliers for dropdown
    cursor.execute("SELECT id, name FROM suppliers WHERE user_id = %s AND deleted_at IS NULL", (session['user_id'],))
    suppliers = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('edit_bill.html',
                         username=session['username'],
                         bill=bill,
                         suppliers=suppliers)

@app.route('/add_supplier', methods=['POST'])
def add_supplier():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
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
    
    return redirect(url_for('ap'))

@app.route('/add_bill', methods=['POST'])
def add_bill():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
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
    
    return redirect(url_for('ap'))

@app.route('/pay_bill/<int:bill_id>')
def pay_bill(bill_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get the bill details
    cursor.execute("""
        SELECT b.*, s.name as supplier_name 
        FROM bills b
        JOIN suppliers s ON b.supplier_id = s.id
        WHERE b.id = %s AND b.user_id = %s
    """, (bill_id, session['user_id']))
    bill = cursor.fetchone()
    
    if bill and bill['status'] == 'unpaid':
        # Mark bill as paid
        cursor.execute("""
            UPDATE bills SET status = 'paid' 
            WHERE id = %s AND user_id = %s
        """, (bill_id, session['user_id']))
        
        # Create a cash transaction for the payment (EXPENSE)
        from datetime import date
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
    
    return redirect(url_for('ap'))

# ========== INVENTORY MODULE ==========
from functools import wraps

@app.route('/inventory')
#@require_feature('inventory_management')
def inventory():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get all products (excluding soft-deleted)
    cursor.execute("""
        SELECT * FROM products 
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY name
    """, (session['user_id'],))
    products = cursor.fetchall()
    
    # Calculate total stock value (excluding soft-deleted)
    total_value = sum(p['quantity'] * p['price'] for p in products)
    
    # Get low stock products (quantity < reorder_level)
    low_stock = [p for p in products if p['quantity'] < p['reorder_level']]
    
    cursor.close()
    db.close()
    
    return render_template('inventory.html',
                         username=session['username'],
                         products=products,
                         total_value=total_value,
                         low_stock=low_stock)

@app.route('/add_product', methods=['POST'])
def add_product():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    name = request.form['name']
    price = float(request.form['price'])
    quantity = int(request.form.get('quantity', 0))
    category = request.form.get('category', '')
    description = request.form.get('description', '')
    reorder_level = int(request.form.get('reorder_level', 5))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO products (user_id, name, description, quantity, price, category, reorder_level)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (session['user_id'], name, description, quantity, price, category, reorder_level))
    db.commit()
    cursor.close()
    db.close()
    
    return redirect(url_for('inventory'))

@app.route('/adjust_stock/<int:product_id>', methods=['POST'])
def adjust_stock(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    quantity = int(request.form['quantity'])
    action = request.form['action']
    
    db = get_db()
    cursor = db.cursor()
    
    if action == 'add':
        cursor.execute("UPDATE products SET quantity = quantity + %s WHERE id = %s AND user_id = %s", 
                      (quantity, product_id, session['user_id']))
    elif action == 'remove':
        cursor.execute("UPDATE products SET quantity = quantity - %s WHERE id = %s AND user_id = %s AND quantity >= %s", 
                      (quantity, product_id, session['user_id'], quantity))
    
    db.commit()
    cursor.close()
    db.close()
    
    return redirect(url_for('inventory'))

@app.route('/delete_product/<int:product_id>')
def delete_product(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get product before deletion (for audit)
    cursor.execute("SELECT * FROM products WHERE id = %s AND user_id = %s", 
                   (product_id, session['user_id']))
    product = cursor.fetchone()
    
    if product and product.get('deleted_at') is None:
        # Soft delete
        cursor.execute("""
            UPDATE products SET deleted_at = NOW() 
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (product_id, session['user_id']))
        db.commit()
        
        # Log to audit (if you have log_audit function)
        # log_audit(session['user_id'], session['username'], 'DELETE', 'products', 
        #           product_id, old_values=product)
    
    cursor.close()
    db.close()
    
    return redirect(url_for('inventory'))

@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        # Get old values first (for audit)
        cursor.execute("SELECT * FROM products WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                       (product_id, session['user_id']))
        old_product = cursor.fetchone()
        
        if not old_product:
            cursor.close()
            db.close()
            return redirect(url_for('inventory'))
        
        # Get new values from form
        name = request.form['name']
        price = float(request.form['price'])
        quantity = int(request.form.get('quantity', 0))
        category = request.form.get('category', '')
        description = request.form.get('description', '')
        reorder_level = int(request.form.get('reorder_level', 5))
        
        # Update product
        cursor.execute("""
            UPDATE products 
            SET name = %s, price = %s, quantity = %s, category = %s, 
                description = %s, reorder_level = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (name, price, quantity, category, description, reorder_level, 
              product_id, session['user_id']))
        db.commit()
        
        # Get new values after update
        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        new_product = cursor.fetchone()
        
        # Log to audit (if you have log_audit function)
        # log_audit(session['user_id'], session['username'], 'UPDATE', 'products', 
        #           product_id, old_values=old_product, new_values=new_product)
        
        cursor.close()
        db.close()
        return redirect(url_for('inventory'))
    
    # GET request - show edit form
    cursor.execute("SELECT * FROM products WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                   (product_id, session['user_id']))
    product = cursor.fetchone()
    
    if not product:
        cursor.close()
        db.close()
        return redirect(url_for('inventory'))
    
    cursor.close()
    db.close()
    
    return render_template('edit_product.html',
                         username=session['username'],
                         product=product)
    
# ========== BUSINESS INSIGHTS ==========
from datetime import datetime, timedelta

def get_week_range(date_obj):
    """Returns Monday and Sunday of the week containing date_obj"""
    # Get Monday (weekday() where Monday = 0, Sunday = 6)
    start_of_week = date_obj - timedelta(days=date_obj.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week

# ========== BUSINESS INSIGHTS (COMPLETE) ==========
from datetime import datetime, timedelta

def get_week_range(date_obj):
    """Returns Monday and Sunday of the week containing date_obj"""
    start_of_week = date_obj - timedelta(days=date_obj.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week

@app.route('/insights')
def insights():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get current date and week ranges
    today = date.today()
    current_week_start, current_week_end = get_week_range(today)
    last_week_start = current_week_start - timedelta(days=7)
    last_week_end = current_week_end - timedelta(days=7)
    
    # ========== SALES DATA ==========
    cursor.execute("""
        SELECT SUM(amount) as total FROM sales 
        WHERE user_id = %s AND sale_date BETWEEN %s AND %s
    """, (session['user_id'], current_week_start, current_week_end))
    result = cursor.fetchone()
    current_sales = float(result['total']) if result['total'] else 0.0
    
    cursor.execute("""
        SELECT SUM(amount) as total FROM sales 
        WHERE user_id = %s AND sale_date BETWEEN %s AND %s
    """, (session['user_id'], last_week_start, last_week_end))
    result = cursor.fetchone()
    last_sales = float(result['total']) if result['total'] else 0.0
    
    # ========== EXPENSE DATA ==========
    cursor.execute("""
        SELECT SUM(amount) as total FROM transactions 
        WHERE user_id = %s AND type = 'expense' 
        AND transaction_date BETWEEN %s AND %s
    """, (session['user_id'], current_week_start, current_week_end))
    result = cursor.fetchone()
    current_expenses = float(result['total']) if result['total'] else 0.0
    
    cursor.execute("""
        SELECT SUM(amount) as total FROM transactions 
        WHERE user_id = %s AND type = 'expense' 
        AND transaction_date BETWEEN %s AND %s
    """, (session['user_id'], last_week_start, last_week_end))
    result = cursor.fetchone()
    last_expenses = float(result['total']) if result['total'] else 0.0
    
    # ========== EXPENSES BY CATEGORY (for alerts) ==========
    cursor.execute("""
        SELECT category, SUM(amount) as total FROM transactions 
        WHERE user_id = %s AND type = 'expense' 
        AND transaction_date BETWEEN %s AND %s
        GROUP BY category
    """, (session['user_id'], current_week_start, current_week_end))
    current_expenses_by_category = {}
    for row in cursor.fetchall():
        if row['category']:
            current_expenses_by_category[row['category']] = float(row['total'])
    
    cursor.execute("""
        SELECT category, SUM(amount) as total FROM transactions 
        WHERE user_id = %s AND type = 'expense' 
        AND transaction_date BETWEEN %s AND %s
        GROUP BY category
    """, (session['user_id'], last_week_start, last_week_end))
    last_expenses_by_category = {}
    for row in cursor.fetchall():
        if row['category']:
            last_expenses_by_category[row['category']] = float(row['total'])
    
    # ========== PROFIT CALCULATIONS ==========
    current_profit = current_sales - current_expenses
    last_profit = last_sales - last_expenses
    
    # ========== HELPER FUNCTION FOR PERCENTAGE CHANGE ==========
    def calc_change(current, last):
        if last == 0:
            return 0.0 if current == 0 else 100.0
        return ((current - last) / last) * 100.0
    
    sales_change = calc_change(current_sales, last_sales)
    expense_change = calc_change(current_expenses, last_expenses)
    profit_change = calc_change(current_profit, last_profit)
    
    # ========== PROFIT MARGIN ==========
    profit_margin = (current_profit / current_sales * 100.0) if current_sales > 0 else 0.0
    
    # ========== SECTION 2: SMART ALERTS ==========
    alerts = []
    
    # Alert 1: Expense category spikes (>20% increase)
    for category, current_amount in current_expenses_by_category.items():
        last_amount = last_expenses_by_category.get(category, 0.0)
        if last_amount > 0:
            increase_pct = ((current_amount - last_amount) / last_amount) * 100.0
            if increase_pct > 20:
                alerts.append({
                    'type': 'expense_spike',
                    'severity': 'high',
                    'category': category,
                    'current': current_amount,
                    'last': last_amount,
                    'increase_pct': increase_pct,
                    'message': f"{category} increased by {increase_pct:.0f}% this week"
                })
    
    # Alert 2: Sales drop (>10% decrease)
    if last_sales > 0 and sales_change < -10:
        alerts.append({
            'type': 'sales_drop',
            'severity': 'medium',
            'current': current_sales,
            'last': last_sales,
            'drop_pct': -sales_change,
            'message': f"Sales dropped by {-sales_change:.0f}% this week"
        })
    
    # Alert 3: Profit decline (>10% decrease)
    if last_profit > 0 and profit_change < -10:
        alerts.append({
            'type': 'profit_decline',
            'severity': 'high',
            'current': current_profit,
            'last': last_profit,
            'decline_pct': -profit_change,
            'message': f"Profit declined by {-profit_change:.0f}% this week"
        })
    
    # ========== SECTION 3: RECOMMENDATIONS ==========
    recommendations = []
    
    for alert in alerts:
        if alert['type'] == 'expense_spike':
            normal_amount = alert['last']
            spike_amount = alert['current']
            excess = spike_amount - normal_amount
            
            recommendations.append({
                'type': 'cost_cutting',
                'category': alert['category'],
                'current': spike_amount,
                'normal': normal_amount,
                'excess': excess,
                'action': f"Review {alert['category']} spending. You spent ₱{excess:,.0f} more than last week.",
                'potential_savings': excess * 0.5,
                'message': f"Reduce {alert['category']} by 50% to save ₱{excess * 0.5:,.0f}"
            })
        
        elif alert['type'] == 'sales_drop':
            recommendations.append({
                'type': 'sales_improvement',
                'drop_pct': alert['drop_pct'],
                'current': alert['current'],
                'last': alert['last'],
                'action': f"Investigate why sales dropped by {alert['drop_pct']:.0f}%. Consider a promotion.",
                'potential_gain': alert['last'] * 0.1,
                'message': f"A 10% sales increase would add ₱{alert['last'] * 0.1:,.0f}"
            })
        
        elif alert['type'] == 'profit_decline':
            recommendations.append({
                'type': 'profit_improvement',
                'decline_pct': alert['decline_pct'],
                'action': f"Review both sales and expenses. Profit dropped {alert['decline_pct']:.0f}%.",
                'message': f"Focus on high-margin products and reduce unnecessary costs"
            })
    
    if not recommendations:
        if profit_margin < 20:
            recommendations.append({
                'type': 'margin_improvement',
                'action': f"Your profit margin is {profit_margin:.0f}%. Industry average is 30-40%.",
                'message': "Try reducing costs or increasing prices by 5-10%"
            })
        else:
            recommendations.append({
                'type': 'maintain',
                'action': "Your business is performing well. Continue monitoring weekly trends.",
                'message': "Keep tracking expenses and look for growth opportunities"
            })
    
    # ========== SECTION 4: PREDICTIVE PLANNER ==========
    # Ensure baseline values are floats
    baseline_sales = float(current_sales) if current_sales > 0 else 100000.0
    baseline_expenses = float(current_expenses) if current_expenses > 0 else 70000.0
    baseline_profit = float(current_profit)
    
    # Pre-calculate scenarios
    scenarios = {
        'price_up_10': {
            'name': 'Raise prices by 10%',
            'sales_change_pct': 10,
            'volume_change_pct': -3,
            'new_sales': baseline_sales * 1.10 * 0.97,
            'new_profit': (baseline_sales * 1.10 * 0.97) - baseline_expenses,
            'profit_change': ((baseline_sales * 1.10 * 0.97) - baseline_expenses) - baseline_profit
        },
        'price_down_5': {
            'name': 'Lower prices by 5%',
            'sales_change_pct': -5,
            'volume_change_pct': 8,
            'new_sales': baseline_sales * 0.95 * 1.08,
            'new_profit': (baseline_sales * 0.95 * 1.08) - baseline_expenses,
            'profit_change': ((baseline_sales * 0.95 * 1.08) - baseline_expenses) - baseline_profit
        },
        'cut_expenses_10': {
            'name': 'Cut expenses by 10%',
            'new_expenses': baseline_expenses * 0.90,
            'new_profit': baseline_sales - (baseline_expenses * 0.90),
            'profit_change': (baseline_sales - (baseline_expenses * 0.90)) - baseline_profit
        }
    }
    
    cursor.close()
    db.close()
    
    week_display = f"{current_week_start.strftime('%b %d')} - {current_week_end.strftime('%b %d, %Y')}"
    
    return render_template('insights.html',
                         username=session['username'],
                         week_display=week_display,
                         # Weekly Insights
                         current_sales=current_sales,
                         current_expenses=current_expenses,
                         current_profit=current_profit,
                         last_sales=last_sales,
                         last_expenses=last_expenses,
                         last_profit=last_profit,
                         sales_change=sales_change,
                         expense_change=expense_change,
                         profit_change=profit_change,
                         profit_margin=profit_margin,
                         # Smart Alerts
                         alerts=alerts,
                         # Recommendations
                         recommendations=recommendations,
                         # Predictive Planner
                         baseline_sales=baseline_sales,
                         baseline_expenses=baseline_expenses,
                         current_profit_baseline=baseline_profit,
                         scenarios=scenarios)

# ========== REGISTRATION (with Industry) ==========
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        full_name = request.form['full_name']
        industry = request.form['industry']
        business_size = request.form['business_size']
        
        hashed = hashlib.sha256(password.encode()).hexdigest()
        
        db = get_db()
        cursor = db.cursor(dictionary=True)  # Use dictionary cursor
        
        try:
            # Insert new user with plan_id = 1 (Basic)
            cursor.execute("""
                INSERT INTO users (username, password, role, full_name, industry, business_size, plan_id)
                VALUES (%s, %s, 'admin', %s, %s, %s, 1)
            """, (username, hashed, full_name, industry, business_size))
            db.commit()
            
            # Get the newly created user
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            
            # Set session
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            
            # Set plan in session
            session['plan'] = 'basic'
            session['plan_name'] = 'Basic'
            
            cursor.close()
            db.close()
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            db.rollback()
            cursor.close()
            db.close()
            return render_template('register.html', error=f"Username already exists: {e}")
    
    return render_template('register.html')

    # ========== ADMIN PANEL (Multi-User Management) ==========
from functools import wraps

@app.route('/admin/users')
#@require_feature('multi_user_basic')

def admin_users():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Only check deleted_at IS NULL (no '0000-00-00')
    cursor.execute("""
        SELECT id, username, full_name, role, created_at 
        FROM users 
        ORDER BY created_at ASC
    """)
    
    users = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('admin_users.html', users=users, username=session['username'])

@app.route('/admin/add_user', methods=['POST'])
def admin_add_user():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    username = request.form['username']
    password = request.form['password']
    full_name = request.form['full_name']
    role = request.form['role']
    
    hashed = hashlib.sha256(password.encode()).hexdigest()
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO users (username, password, role, full_name, created_by)
            VALUES (%s, %s, %s, %s, %s)
        """, (username, hashed, role, full_name, session['user_id']))
        db.commit()
    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return f"Error: {e}", 400
    
    cursor.close()
    db.close()
    
    return redirect(url_for('admin_users'))

@app.route('/admin/delete_user/<int:user_id>')
def admin_delete_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    # Cannot delete yourself
    if user_id == session['user_id']:
        return "Cannot delete your own account", 400
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    db.commit()
    cursor.close()
    db.close()
    
    return redirect(url_for('admin_users'))

# ========== OFFLINE SYNC ==========
@app.route('/api/sync_offline', methods=['POST'])
def sync_offline():
    """Endpoint for browser to sync offline transactions when back online"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    offline_transactions = data.get('transactions', [])
    
    db = get_db()
    cursor = db.cursor()
    saved_count = 0
    
    for tx in offline_transactions:
        try:
            cursor.execute("""
                INSERT INTO transactions (user_id, description, amount, type, category, transaction_date)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                session['user_id'],
                tx.get('description'),
                float(tx.get('amount', 0)),
                tx.get('type', 'expense'),
                tx.get('category', ''),
                tx.get('date', date.today())
            ))
            saved_count += 1
        except Exception as e:
            print(f"Error saving offline transaction: {e}")
    
    db.commit()
    cursor.close()
    db.close()
    
    return jsonify({'synced': saved_count, 'total': len(offline_transactions)})

    # ========== VOICE INPUT PARSING ==========
@app.route('/api/parse_voice', methods=['POST'])
def parse_voice():
    """Parse spoken text into transaction fields"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    text = data.get('text', '').lower()
    
    # Simple parsing logic
    result = {
        'description': '',
        'amount': None,
        'type': 'expense',
        'category': ''
    }
    
    # Detect transaction type
    if 'income' in text or 'sale' in text or 'received' in text or 'payment' in text:
        result['type'] = 'income'
    elif 'expense' in text or 'spent' in text or 'paid' in text or 'bought' in text:
        result['type'] = 'expense'
    
    # Extract amount (look for numbers)
    import re
    numbers = re.findall(r'(\d+(?:\.\d+)?)', text)
    if numbers:
        result['amount'] = float(numbers[0])
    
    # Extract description (remove the amount and common words)
    description = text
    if result['amount']:
        description = description.replace(str(int(result['amount'])), '')
    for word in ['income', 'expense', 'sale', 'spent', 'paid', 'received', 'bought', 'for', 'on']:
        description = description.replace(word, '')
    result['description'] = description.strip().capitalize()
    
    # Guess category based on keywords
    if 'rent' in text:
        result['category'] = 'Rent'
    elif 'food' in text or 'supplies' in text or 'ingredients' in text:
        result['category'] = 'Supplies'
    elif 'salary' in text or 'wage' in text or 'staff' in text:
        result['category'] = 'Salaries'
    elif 'electric' in text or 'water' in text or 'utility' in text:
        result['category'] = 'Utilities'
    
    return jsonify(result)

# ========== ADMIN RESTORE PAGE ==========
@app.route('/admin/restore')
def admin_restore():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    # Get filter parameter from URL (default: 'all')
    module_filter = request.args.get('filter', 'all')
    search_query = request.args.get('search', '')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    deleted_items = []
    
    # Helper function to add items with filter check
    def add_items(items, module_name, type_code):
        if module_filter == 'all' or module_filter == module_name:
            for item in items:
                item['module_display'] = module_name
                item['type_code'] = type_code
                # Apply search filter if present
                if search_query:
                    if search_query.lower() in str(item.get('description', '')).lower():
                        deleted_items.append(item)
                else:
                    deleted_items.append(item)
    
    # Deleted transactions (if filter is 'all' or 'transactions')
    if module_filter == 'all' or module_filter == 'transactions':
        cursor.execute("""
            SELECT id, description, amount, transaction_date as date, 'transaction' as module, '💰 Transaction' as module_type
            FROM transactions 
            WHERE user_id = %s AND deleted_at IS NOT NULL
            ORDER BY deleted_at DESC
        """, (session['user_id'],))
        add_items(cursor.fetchall(), 'transactions', 1)
    
    # Deleted sales
    if module_filter == 'all' or module_filter == 'sales':
        cursor.execute("""
            SELECT id, customer_name as description, amount, sale_date as date, 'sale' as module, '📈 Sale' as module_type
            FROM sales 
            WHERE user_id = %s AND deleted_at IS NOT NULL
            ORDER BY deleted_at DESC
        """, (session['user_id'],))
        add_items(cursor.fetchall(), 'sales', 2)
    
    # Deleted invoices
    if module_filter == 'all' or module_filter == 'invoices':
        cursor.execute("""
            SELECT i.id, CONCAT(c.name, ' - ₱', i.amount) as description, i.amount, i.due_date as date, 'invoice' as module, '📄 Invoice' as module_type
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            WHERE i.user_id = %s AND i.deleted_at IS NOT NULL
            ORDER BY i.deleted_at DESC
        """, (session['user_id'],))
        add_items(cursor.fetchall(), 'invoices', 3)
    
    # Deleted bills
    if module_filter == 'all' or module_filter == 'bills':
        cursor.execute("""
            SELECT b.id, CONCAT(s.name, ' - ₱', b.amount) as description, b.amount, b.due_date as date, 'bill' as module, '📃 Bill' as module_type
            FROM bills b
            JOIN suppliers s ON b.supplier_id = s.id
            WHERE b.user_id = %s AND b.deleted_at IS NOT NULL
            ORDER BY b.deleted_at DESC
        """, (session['user_id'],))
        add_items(cursor.fetchall(), 'bills', 4)
    
    # Deleted products
    if module_filter == 'all' or module_filter == 'products':
        cursor.execute("""
            SELECT id, CONCAT(name, ' (', quantity, ' in stock)') as description, price as amount, created_at as date, 'product' as module, '📦 Product' as module_type
            FROM products 
            WHERE user_id = %s AND deleted_at IS NOT NULL
            ORDER BY deleted_at DESC
        """, (session['user_id'],))
        add_items(cursor.fetchall(), 'products', 5)
    
    cursor.close()
    db.close()
    
    # Count items per module for display
    module_counts = {
        'transactions': len([i for i in deleted_items if i.get('module') == 'transaction']),
        'sales': len([i for i in deleted_items if i.get('module') == 'sale']),
        'invoices': len([i for i in deleted_items if i.get('module') == 'invoice']),
        'bills': len([i for i in deleted_items if i.get('module') == 'bill']),
        'products': len([i for i in deleted_items if i.get('module') == 'product'])
    }
    
    return render_template('admin_restore.html',
                         username=session['username'],
                         deleted_items=deleted_items,
                         current_filter=module_filter,
                         search_query=search_query,
                         module_counts=module_counts)

@app.route('/admin/restore/<int:type_code>/<int:record_id>')
def admin_restore_item(type_code, record_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    table_map = {
        1: 'transactions',
        2: 'sales',
        3: 'invoices',
        4: 'bills',
        5: 'products'
    }
    
    table_name = table_map.get(type_code)
    if not table_name:
        return f"Invalid type code: {type_code}", 400
    
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute(f"UPDATE {table_name} SET deleted_at = NULL WHERE id = %s AND user_id = %s", 
                   (record_id, session['user_id']))
    db.commit()
    log_audit(session['user_id'], session['username'], 'RESTORE', table_name, 
          record_id, new_values={'restored_at': str(datetime.now())})
    cursor.close()
    db.close()
    
    return redirect(url_for('admin_restore'))

# ========== AUDIT LOG VIEW PAGE ==========
from functools import wraps

@app.route('/admin/audit')
#@require_feature('audit_log')
def admin_audit():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    # Get filter parameters
    action_filter = request.args.get('action', 'all')
    table_filter = request.args.get('table', 'all')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    query = """
        SELECT * FROM audit_log 
        WHERE user_id = %s
    """
    params = [session['user_id']]
    
    if action_filter != 'all':
        query += " AND action = %s"
        params.append(action_filter)
    
    if table_filter != 'all':
        query += " AND table_name = %s"
        params.append(table_filter)
    
    query += " ORDER BY created_at DESC LIMIT 500"
    
    cursor.execute(query, params)
    logs = cursor.fetchall()
    
    # Get unique actions and tables for filters
    cursor.execute("SELECT DISTINCT action FROM audit_log WHERE user_id = %s", (session['user_id'],))
    actions = [row['action'] for row in cursor.fetchall()]
    
    cursor.execute("SELECT DISTINCT table_name FROM audit_log WHERE user_id = %s", (session['user_id'],))
    tables = [row['table_name'] for row in cursor.fetchall()]
    
    cursor.close()
    db.close()
    
    return render_template('admin_audit.html',
                         username=session['username'],
                         logs=logs,
                         actions=actions,
                         tables=tables,
                         current_action=action_filter,
                         current_table=table_filter)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')