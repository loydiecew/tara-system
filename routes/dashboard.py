from flask import Blueprint, render_template, session, redirect, url_for, request
from datetime import date, timedelta, datetime
from models.database import get_db
import calendar

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    # Get period from query string
    period = request.args.get('period', 'month')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id')
    if not business_id:
        business_id = session['user_id']
    
    today = date.today()
    
    # Set date range based on period
    if period == 'today':
        start_date = today
        end_date = today
        compare_start = today - timedelta(days=1)
        compare_end = today - timedelta(days=1)
        period_label = 'Today'
        compare_label = 'Yesterday'
    elif period == 'week':
        from models.helpers import get_week_range
        start_date, end_date = get_week_range(today)
        compare_start = start_date - timedelta(days=7)
        compare_end = end_date - timedelta(days=7)
        period_label = 'This Week'
        compare_label = 'Last Week'
    else:  # month (or last_month)
        if period == 'last_month':
            # Last month
            start_date = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            if start_date.month == 12:
                end_date = start_date.replace(day=31)
            else:
                end_date = (start_date.replace(month=start_date.month + 1, day=1) - timedelta(days=1))
            period_label = start_date.strftime('%B')
            compare_start = (start_date - timedelta(days=1)).replace(day=1)
            if compare_start.month == 12:
                compare_end = compare_start.replace(day=31)
            else:
                compare_end = (compare_start.replace(month=compare_start.month + 1, day=1) - timedelta(days=1))
            compare_label = compare_start.strftime('%B')
        elif today.day <= 3:
            # Early in month - check if current month has data, fall back to last month
            start_date = today.replace(day=1)
            if today.month == 12:
                end_date = today.replace(day=31)
            else:
                end_date = (today.replace(month=today.month + 1, day=1) - timedelta(days=1))
            
            cursor.execute("""
                SELECT COUNT(*) as count FROM (
                    SELECT t.id FROM transactions t
                    JOIN users u ON t.user_id = u.id
                    WHERE u.business_id = %s AND t.transaction_date >= %s AND t.transaction_date <= %s
                    UNION ALL
                    SELECT s.id FROM sales s
                    JOIN users u ON s.user_id = u.id
                    WHERE u.business_id = %s AND s.sale_date >= %s AND s.sale_date <= %s
                ) AS all_data
            """, (business_id, start_date, end_date, business_id, start_date, end_date))
            current_month_count = cursor.fetchone()['count']
            
            if current_month_count == 0:
                # Fall back to last month
                start_date = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
                if start_date.month == 12:
                    end_date = start_date.replace(day=31)
                else:
                    end_date = (start_date.replace(month=start_date.month + 1, day=1) - timedelta(days=1))
                period = 'last_month'
                period_label = start_date.strftime('%B')
            else:
                period_label = 'This Month'
            
            compare_start = (start_date - timedelta(days=1)).replace(day=1)
            if compare_start.month == 12:
                compare_end = compare_start.replace(day=31)
            else:
                compare_end = (compare_start.replace(month=compare_start.month + 1, day=1) - timedelta(days=1))
            compare_label = compare_start.strftime('%B')
        else:
            # Normal month view
            start_date = today.replace(day=1)
            if today.month == 12:
                end_date = today.replace(day=31)
            else:
                end_date = (today.replace(month=today.month + 1, day=1) - timedelta(days=1))
            period_label = 'This Month'
            compare_start = (start_date - timedelta(days=1)).replace(day=1)
            if compare_start.month == 12:
                compare_end = compare_start.replace(day=31)
            else:
                compare_end = (compare_start.replace(month=compare_start.month + 1, day=1) - timedelta(days=1))
            compare_label = compare_start.strftime('%B')
    
    # ========== CURRENT PERIOD REVENUE (Sales + Cash Income) ==========
    cursor.execute("""
        SELECT SUM(amount) as total FROM (
            SELECT t.amount FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' 
            AND t.transaction_date BETWEEN %s AND %s
            UNION ALL
            SELECT s.amount FROM sales s
            JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
        ) AS all_revenue
    """, (business_id, start_date, end_date, business_id, start_date, end_date))
    current_revenue = float(cursor.fetchone()['total'] or 0)
    
    # ========== CURRENT PERIOD EXPENSES ==========
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, start_date, end_date))
    current_expenses = float(cursor.fetchone()['total'] or 0)
    
    current_profit = current_revenue - current_expenses
    
    # ========== COMPARE PERIOD REVENUE (Sales + Cash Income) ==========
    cursor.execute("""
        SELECT SUM(amount) as total FROM (
            SELECT t.amount FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' 
            AND t.transaction_date BETWEEN %s AND %s
            UNION ALL
            SELECT s.amount FROM sales s
            JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
        ) AS all_revenue
    """, (business_id, compare_start, compare_end, business_id, compare_start, compare_end))
    compare_revenue = float(cursor.fetchone()['total'] or 0)
    
    # ========== COMPARE PERIOD EXPENSES ==========
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, compare_start, compare_end))
    compare_expenses = float(cursor.fetchone()['total'] or 0)
    
    compare_profit = compare_revenue - compare_expenses
    
    # ========== HELPER FUNCTION FOR PERCENTAGE CHANGE ==========
    def calc_change(current, last):
        if last == 0:
            return 0.0 if current == 0 else 100.0
        return ((current - last) / last) * 100.0
    
    revenue_change = calc_change(current_revenue, compare_revenue)
    expense_change = calc_change(current_expenses, compare_expenses)
    profit_change = calc_change(current_profit, compare_profit)
    profit_margin = (current_profit / current_revenue * 100) if current_revenue > 0 else 0
    
    # ========== CASH BALANCE (all time) ==========
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
    
    # ========== AR OUTSTANDING ==========
    cursor.execute("""
        SELECT COALESCE(SUM(i.amount), 0) as total_invoiced
        FROM invoices i
        JOIN users u ON i.user_id = u.id
        WHERE u.business_id = %s AND i.status IN ('unpaid', 'partially_paid') AND i.deleted_at IS NULL
    """, (business_id,))
    total_invoiced = float(cursor.fetchone()['total_invoiced'] or 0)
    
    cursor.execute("""
        SELECT COALESCE(SUM(p.amount), 0) as total_paid
        FROM payments p
        JOIN invoices i ON p.invoice_id = i.id
        JOIN users u ON i.user_id = u.id
        WHERE u.business_id = %s AND i.deleted_at IS NULL
    """, (business_id,))
    total_ar_paid = float(cursor.fetchone()['total_paid'] or 0)
    
    ar_outstanding = total_invoiced - total_ar_paid

    # ========== AP OUTSTANDING ==========
    cursor.execute("""
        SELECT COALESCE(SUM(b.amount), 0) as total_billed
        FROM bills b
        JOIN users u ON b.user_id = u.id
        WHERE u.business_id = %s AND b.status IN ('unpaid', 'partially_paid') AND b.deleted_at IS NULL
    """, (business_id,))
    total_billed = float(cursor.fetchone()['total_billed'] or 0)
    
    cursor.execute("""
        SELECT COALESCE(SUM(p.amount), 0) as total_paid
        FROM payments p
        JOIN bills b ON p.bill_id = b.id
        JOIN users u ON b.user_id = u.id
        WHERE u.business_id = %s AND b.deleted_at IS NULL
    """, (business_id,))
    total_ap_paid = float(cursor.fetchone()['total_paid'] or 0)
    
    ap_outstanding = total_billed - total_ap_paid

    # ========== INVENTORY SUMMARY ==========
    cursor.execute("""
        SELECT 
            SUM(p.quantity * p.price) as total_value,
            COUNT(*) as total_products,
            SUM(CASE WHEN p.quantity < p.reorder_level THEN 1 ELSE 0 END) as low_stock_count
        FROM products p
        JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.deleted_at IS NULL
    """, (business_id,))
    inv_summary = cursor.fetchone()
    inventory_value = float(inv_summary['total_value'] or 0)
    total_products = inv_summary['total_products'] or 0
    low_stock_count = inv_summary['low_stock_count'] or 0
    
    # ========== RECENT TRANSACTIONS ==========
    cursor.execute("""
        SELECT t.* FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s 
        ORDER BY t.transaction_date DESC 
        LIMIT 10
    """, (business_id,))
    recent = cursor.fetchall()
    
    # ========== CALENDAR HEATMAP DATA ==========
    heatmap_start = today - timedelta(days=365)
    
    cursor.execute("""
        SELECT sale_date, SUM(amount) as total
        FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.sale_date >= %s
        GROUP BY sale_date
        ORDER BY sale_date ASC
    """, (business_id, heatmap_start))
    daily_sales = cursor.fetchall()
    
    cursor.execute("""
        SELECT transaction_date, SUM(amount) as total
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date >= %s
        GROUP BY transaction_date
        ORDER BY transaction_date ASC
    """, (business_id, heatmap_start))
    daily_income = cursor.fetchall()
    
    heatmap_dict = {}
    for d in daily_sales:
        key = d['sale_date'].isoformat() if hasattr(d['sale_date'], 'isoformat') else str(d['sale_date'])
        heatmap_dict[key] = float(d['total'] or 0)
    for d in daily_income:
        key = d['transaction_date'].isoformat() if hasattr(d['transaction_date'], 'isoformat') else str(d['transaction_date'])
        heatmap_dict[key] = heatmap_dict.get(key, 0) + float(d['total'] or 0)
    
    import json
    heatmap_data = json.dumps([{'date': k, 'amount': v} for k, v in heatmap_dict.items()])

    # ========== ALERTS ==========
    alerts = []
    
    # Overdue invoices
    cursor.execute("""
        SELECT COUNT(*) as count, SUM(i.amount) as total
        FROM invoices i
        JOIN users u ON i.user_id = u.id
        WHERE u.business_id = %s AND i.status IN ('unpaid', 'partially_paid')
        AND i.due_date < %s AND i.deleted_at IS NULL
    """, (business_id, today))
    overdue = cursor.fetchone()
    if overdue['count'] > 0:
        alerts.append({
            'type': 'overdue',
            'icon': 'fa-exclamation-circle',
            'color': '#ef4444',
            'message': f"{overdue['count']} invoice{'s' if overdue['count'] > 1 else ''} overdue",
            'detail': f"₱{float(overdue['total'] or 0):,.0f} outstanding",
            'link': '/ar'
        })
    
    # Low stock products
    cursor.execute("""
        SELECT COUNT(*) as count FROM products p
        JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.quantity < p.reorder_level AND p.deleted_at IS NULL
    """, (business_id,))
    low_stock = cursor.fetchone()
    if low_stock['count'] > 0:
        alerts.append({
            'type': 'low_stock',
            'icon': 'fa-box-open',
            'color': '#f59e0b',
            'message': f"{low_stock['count']} product{'s' if low_stock['count'] > 1 else ''} low stock",
            'detail': 'Reorder now to avoid stockout',
            'link': '/inventory'
        })
    
    # Expense spike (this week vs last week)
    from models.helpers import get_week_range
    this_week_start, this_week_end = get_week_range(today)
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end = this_week_end - timedelta(days=7)
    
    cursor.execute("""
        SELECT SUM(amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense'
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, this_week_start, this_week_end))
    this_week_exp = float(cursor.fetchone()['total'] or 0)
    
    cursor.execute("""
        SELECT SUM(amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense'
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, last_week_start, last_week_end))
    last_week_exp = float(cursor.fetchone()['total'] or 0)
    
    if last_week_exp > 0:
        expense_spike = ((this_week_exp - last_week_exp) / last_week_exp) * 100
        if expense_spike > 20:
            alerts.append({
                'type': 'expense_spike',
                'icon': 'fa-arrow-trend-up',
                'color': '#f97316',
                'message': f'Expenses up {expense_spike:.0f}% this week',
                'detail': f'₱{this_week_exp:,.0f} vs ₱{last_week_exp:,.0f} last week',
                'link': '/insights'
            })
    
    # Sales drop (this week vs last week)
    cursor.execute("""
        SELECT SUM(amount) as total FROM (
            SELECT t.amount FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date BETWEEN %s AND %s
            UNION ALL
            SELECT s.amount FROM sales s
            JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
        ) AS revenue
    """, (business_id, this_week_start, this_week_end, business_id, this_week_start, this_week_end))
    this_week_rev = float(cursor.fetchone()['total'] or 0)
    
    cursor.execute("""
        SELECT SUM(amount) as total FROM (
            SELECT t.amount FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date BETWEEN %s AND %s
            UNION ALL
            SELECT s.amount FROM sales s
            JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
        ) AS revenue
    """, (business_id, last_week_start, last_week_end, business_id, last_week_start, last_week_end))
    last_week_rev = float(cursor.fetchone()['total'] or 0)
    
    if last_week_rev > 0:
        sales_drop = ((this_week_rev - last_week_rev) / last_week_rev) * 100
        if sales_drop < -10:
            alerts.append({
                'type': 'sales_drop',
                'icon': 'fa-arrow-trend-down',
                'color': '#3b82f6',
                'message': f'Sales down {abs(sales_drop):.0f}% this week',
                'detail': f'₱{this_week_rev:,.0f} vs ₱{last_week_rev:,.0f} last week',
                'link': '/insights'
            })

    cursor.close()
    db.close()
    
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
                         monthly_income=current_revenue,
                         monthly_expense=current_expenses,
                         profit=current_profit,
                         sales_change=revenue_change,
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
                         today=now.strftime('%B %d, %Y'),
                         heatmap_data=heatmap_data,
                         alerts=alerts,
                         period=period,
                         period_label=period_label,
                         compare_label=compare_label)