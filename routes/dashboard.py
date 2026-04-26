from flask import Blueprint, render_template, session, redirect, url_for
from datetime import date, timedelta, datetime
from models.database import get_db

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get business_id from session
    business_id = session.get('business_id')
    if not business_id:
        business_id = session['user_id']
    
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
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'income' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, first_day, last_day))
    monthly_income = float(cursor.fetchone()['total'] or 0)
    
    # Monthly expense
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, first_day, last_day))
    monthly_expense = float(cursor.fetchone()['total'] or 0)
    
    current_profit = monthly_income - monthly_expense
    
    # Last month income
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'income' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, last_month_first, last_month_last))
    last_monthly_income = float(cursor.fetchone()['total'] or 0)
    
    # Last month expense
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, last_month_first, last_month_last))
    last_monthly_expense = float(cursor.fetchone()['total'] or 0)
    
    last_profit = last_monthly_income - last_monthly_expense
    
    def calc_change(current, last):
        if last == 0:
            return 0.0 if current == 0 else 100.0
        return ((current - last) / last) * 100.0
    
    sales_change = calc_change(monthly_income, last_monthly_income)
    expense_change = calc_change(monthly_expense, last_monthly_expense)
    profit_change = calc_change(current_profit, last_profit)
    profit_margin = (current_profit / monthly_income * 100) if monthly_income > 0 else 0
    
    # Cash balance
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN t.type = 'income' THEN t.amount ELSE 0 END) as total_income,
            SUM(CASE WHEN t.type = 'expense' THEN t.amount ELSE 0 END) as total_expense
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s
    """, (business_id,))
    totals = cursor.fetchone()
    cash_balance = (float(totals['total_income'] or 0)) - (float(totals['total_expense'] or 0))
    
    # AR Outstanding
    cursor.execute("""
        SELECT SUM(i.amount) as total FROM invoices i
        JOIN users u ON i.user_id = u.id
        WHERE u.business_id = %s AND i.status = 'unpaid'
    """, (business_id,))
    ar_outstanding = float(cursor.fetchone()['total'] or 0)
    
    # AP Outstanding
    cursor.execute("""
        SELECT SUM(b.amount) as total FROM bills b
        JOIN users u ON b.user_id = u.id
        WHERE u.business_id = %s AND b.status = 'unpaid'
    """, (business_id,))
    ap_outstanding = float(cursor.fetchone()['total'] or 0)
    
    # Inventory Summary
    cursor.execute("""
        SELECT 
            SUM(p.quantity * p.price) as total_value,
            COUNT(*) as total_products,
            SUM(CASE WHEN p.quantity < p.reorder_level THEN 1 ELSE 0 END) as low_stock_count
        FROM products p
        JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s
    """, (business_id,))
    inv_summary = cursor.fetchone()
    inventory_value = float(inv_summary['total_value'] or 0)
    total_products = inv_summary['total_products'] or 0
    low_stock_count = inv_summary['low_stock_count'] or 0
    
    # Recent transactions
    cursor.execute("""
        SELECT t.* FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s 
        ORDER BY t.transaction_date DESC 
        LIMIT 10
    """, (business_id,))
    recent = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    # Get greeting
    now = datetime.now()
    current_hour = now.hour
    if current_hour < 12:
        greeting = "Morning"
    elif current_hour < 18:
        greeting = "Afternoon"
    else:
        greeting = "Evening"
    
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
                         transactions=recent,
                         greeting=greeting,
                         today=now.strftime('%B %d, %Y'))