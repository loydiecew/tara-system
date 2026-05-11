from flask import Blueprint, render_template, session, redirect, url_for, jsonify, request
from datetime import date, timedelta
import json
from models.database import get_db
from models.helpers import get_week_range

insights_bp = Blueprint('insights', __name__)

@insights_bp.route('/insights')
def insights():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    is_cashier = session.get('role') == 'cashier'
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    today = date.today()
    
    # Get period from query string
    period = request.args.get('period', 'month')
    
    if period == 'quarter':
        quarter = (today.month - 1) // 3
        start_date = date(today.year, quarter * 3 + 1, 1)
        end_date = today
        compare_start = (start_date - timedelta(days=1))
        compare_start = date(compare_start.year, ((compare_start.month-1)//3)*3 + 1, 1)
        compare_end = start_date - timedelta(days=1)
    elif period == 'year':
        start_date = date(today.year, 1, 1)
        end_date = today
        compare_start = date(today.year - 1, 1, 1)
        compare_end = date(today.year - 1, 12, 31)
    elif len(period) == 7 and '-' in period:
        year, month = map(int, period.split('-'))
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year, month, 31)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        compare_start = (start_date - timedelta(days=1)).replace(day=1)
        if compare_start.month == 12:
            compare_end = compare_start.replace(day=31)
        else:
            compare_end = (compare_start.replace(month=compare_start.month + 1, day=1) - timedelta(days=1))
    else:
        start_date = today.replace(day=1)
        if today.month == 12:
            end_date = today.replace(day=31)
        else:
            end_date = (today.replace(month=today.month + 1, day=1) - timedelta(days=1))
        compare_start = (start_date - timedelta(days=1)).replace(day=1)
        if compare_start.month == 12:
            compare_end = compare_start.replace(day=31)
        else:
            compare_end = (compare_start.replace(month=compare_start.month + 1, day=1) - timedelta(days=1))
    
    # Revenue
    cursor.execute("""
        SELECT SUM(amount) as total FROM (
            SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date BETWEEN %s AND %s AND t.status != 'void'
            UNION ALL
            SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
        ) AS revenue
    """, (business_id, start_date, end_date, business_id, start_date, end_date))
    current_revenue = float(cursor.fetchone()['total'] or 0)
    
    # Expenses
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date BETWEEN %s AND %s AND t.status != 'void'
    """, (business_id, start_date, end_date))
    current_expenses = float(cursor.fetchone()['total'] or 0)
    current_profit = current_revenue - current_expenses
    
    # Compare period
    cursor.execute("""
        SELECT SUM(amount) as total FROM (
            SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date BETWEEN %s AND %s AND t.status != 'void'
            UNION ALL
            SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
        ) AS revenue
    """, (business_id, compare_start, compare_end, business_id, compare_start, compare_end))
    compare_revenue = float(cursor.fetchone()['total'] or 0)
    
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date BETWEEN %s AND %s AND t.status != 'void'
    """, (business_id, compare_start, compare_end))
    compare_expenses = float(cursor.fetchone()['total'] or 0)
    compare_profit = compare_revenue - compare_expenses
    
    def calc_change(current, last):
        if last == 0: return 0.0 if current == 0 else 100.0
        return ((current - last) / last) * 100.0
    
    revenue_change = calc_change(current_revenue, compare_revenue)
    expense_change = calc_change(current_expenses, compare_expenses)
    profit_change = calc_change(current_profit, compare_profit)
    profit_margin = (current_profit / current_revenue * 100) if current_revenue > 0 else 0
    
    # Available months for dropdown
    cursor.execute("""
        SELECT DISTINCT DATE_FORMAT(d, '%Y-%m') as month FROM (
            SELECT transaction_date as d FROM transactions t JOIN users u ON t.user_id = u.id WHERE u.business_id = %s
            UNION SELECT sale_date FROM sales s JOIN users u ON s.user_id = u.id WHERE u.business_id = %s
        ) AS dates ORDER BY month DESC LIMIT 24
    """, (business_id, business_id))
    available_months = [row['month'] for row in cursor.fetchall()]
    
    # Monthly comparison data (last 12 months)
    monthly_data = []
    for i in range(11, -1, -1):
        m_start = (today.replace(day=1) - timedelta(days=i*30)).replace(day=1)
        if m_start.month == 12:
            m_end = m_start.replace(day=31)
        else:
            m_end = (m_start.replace(month=m_start.month + 1, day=1) - timedelta(days=1))
        
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) as rev FROM (
                SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
                WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date BETWEEN %s AND %s AND t.status != 'void'
                UNION ALL
                SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
                WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
            ) AS r
        """, (business_id, m_start, m_end, business_id, m_start, m_end))
        rev = float(cursor.fetchone()['rev'] or 0)
        
        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) as exp FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date BETWEEN %s AND %s AND t.status != 'void'
        """, (business_id, m_start, m_end))
        exp = float(cursor.fetchone()['exp'] or 0)
        
        monthly_data.append({
            'month': m_start.strftime('%b %Y'),
            'revenue': rev,
            'expenses': exp,
            'profit': rev - exp
        })
    
    # Alerts (enhanced)
    alerts = []
    
    # Overdue invoices
    cursor.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(i.amount), 0) as total
        FROM invoices i JOIN users u ON i.user_id = u.id
        WHERE u.business_id = %s AND i.status IN ('unpaid', 'partially_paid') AND i.due_date < %s AND i.deleted_at IS NULL
    """, (business_id, today))
    overdue = cursor.fetchone()
    if overdue['count'] > 0:
        alerts.append({'type': 'overdue', 'severity': 'high', 'message': f"{overdue['count']} invoice{'s' if overdue['count']>1 else ''} overdue", 'detail': f"₱{float(overdue['total']):,.0f} outstanding", 'link': '/ar'})
    
    # Low stock
    cursor.execute("""
        SELECT COUNT(*) as count FROM products p JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.quantity < p.reorder_level AND p.deleted_at IS NULL
    """, (business_id,))
    low = cursor.fetchone()
    if low['count'] > 0:
        alerts.append({'type': 'low_stock', 'severity': 'medium', 'message': f"{low['count']} product{'s' if low['count']>1 else ''} low stock", 'detail': 'Reorder now', 'link': '/inventory'})
    
    # Bills due this week
    week_end = today + timedelta(days=7)
    cursor.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(b.amount), 0) as total FROM bills b JOIN users u ON b.user_id = u.id
        WHERE u.business_id = %s AND b.status = 'unpaid' AND b.due_date BETWEEN %s AND %s AND b.deleted_at IS NULL
    """, (business_id, today, week_end))
    bills_due = cursor.fetchone()
    if bills_due['count'] > 0:
        alerts.append({'type': 'bills_due', 'severity': 'medium', 'message': f"{bills_due['count']} bill{'s' if bills_due['count']>1 else ''} due this week", 'detail': f"₱{float(bills_due['total']):,.0f} to pay", 'link': '/ap'})
    
    # Revenue decline (vs last month)
    if revenue_change < -10:
        alerts.append({'type': 'revenue_decline', 'severity': 'medium', 'message': f'Revenue down {abs(revenue_change):.0f}% vs last period', 'detail': 'Review sales strategy', 'link': '/insights'})
    
    # Expense spike
    if expense_change > 20:
        alerts.append({'type': 'expense_spike', 'severity': 'high', 'message': f'Expenses up {expense_change:.0f}% vs last period', 'detail': 'Review spending', 'link': '/insights'})
    
    # Recommendations
    recommendations = []
    if profit_margin < 20:
        recommendations.append({'type': 'margin', 'action': f'Profit margin is {profit_margin:.0f}%. Target 30-40%.', 'detail': 'Reduce costs or increase prices by 5-10%'})
    if current_expenses > current_revenue * 0.8:
        recommendations.append({'type': 'cost', 'action': 'Expenses are over 80% of revenue.', 'detail': 'Review top expense categories'})
    if overdue['count'] > 0:
        recommendations.append({'type': 'collection', 'action': f'{overdue["count"]} overdue invoice{"s" if overdue["count"]>1 else ""}.', 'detail': 'Send payment reminders'})
    if low['count'] > 0:
        recommendations.append({'type': 'inventory', 'action': f'{low["count"]} product{"s" if low["count"]>1 else ""} low stock.', 'detail': 'Create purchase orders'})
    if not recommendations:
        recommendations.append({'type': 'positive', 'action': 'Your business is performing well.', 'detail': 'Keep monitoring trends'})
    
    cursor.close()
    db.close()
    
    period_label = f"{start_date.strftime('%b %d, %Y')} — {end_date.strftime('%b %d, %Y')}"
    
    return render_template('insights.html',
                         username=session['username'],
                         current_sales=current_revenue,
                         current_expenses=current_expenses,
                         current_profit=current_profit,
                         sales_change=revenue_change,
                         expense_change=expense_change,
                         profit_change=profit_change,
                         profit_margin=profit_margin,
                         alerts=alerts,
                         recommendations=recommendations,
                         available_months=available_months,
                         monthly_data=monthly_data,
                         period=period,
                         period_label=period_label,
                         is_cashier=is_cashier)

# ========== ENHANCED BUSINESS INSIGHTS API ENDPOINTS ==========

@insights_bp.route('/api/product-profitability')
def product_profitability():
    """Get profitability report per product"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    period = request.args.get('period', 'month')
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get date range
    today = date.today()
    if period == 'month':
        start_date = today.replace(day=1)
        end_date = today
    elif period == 'quarter':
        quarter = (today.month - 1) // 3
        start_date = date(today.year, quarter * 3 + 1, 1)
        end_date = today
    elif period == 'year':
        start_date = date(today.year, 1, 1)
        end_date = today
    else:
        start_date = today - timedelta(days=30)
        end_date = today
    
    # Get sales by product
    cursor.execute("""
        SELECT 
            p.id,
            p.name,
            p.price,
            p.cogs,
            SUM(s.amount) as total_sales,
            COUNT(s.id) as units_sold
        FROM products p
        LEFT JOIN sales s ON s.description LIKE CONCAT('%', p.name, '%')
        JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.deleted_at IS NULL
        AND (s.sale_date BETWEEN %s AND %s OR s.sale_date IS NULL)
        GROUP BY p.id
        ORDER BY total_sales DESC
    """, (business_id, start_date, end_date))
    products = cursor.fetchall()
    
    result = []
    total_revenue = 0
    for p in products:
        revenue = float(p['total_sales'] or 0)
        cogs = float(p['cogs'] or 0) * int(p['units_sold'] or 0)
        profit = revenue - cogs
        margin = (profit / revenue * 100) if revenue > 0 else 0
        
        total_revenue += revenue
        
        result.append({
            'id': p['id'],
            'name': p['name'],
            'revenue': revenue,
            'cogs': cogs,
            'profit': profit,
            'margin': round(margin, 1),
            'units_sold': int(p['units_sold'] or 0)
        })
    
    cursor.close()
    db.close()
    
    return jsonify({
        'products': result,
        'total_revenue': total_revenue,
        'period': period
    })


@insights_bp.route('/api/customer-ranking')
def customer_ranking():
    """Get top customers by sales"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    period = request.args.get('period', 'month')
    limit = int(request.args.get('limit', 10))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get date range
    today = date.today()
    if period == 'month':
        start_date = today.replace(day=1)
        end_date = today
    elif period == 'quarter':
        quarter = (today.month - 1) // 3
        start_date = date(today.year, quarter * 3 + 1, 1)
        end_date = today
    elif period == 'year':
        start_date = date(today.year, 1, 1)
        end_date = today
    else:
        start_date = today - timedelta(days=30)
        end_date = today
    
    cursor.execute("""
        SELECT 
            s.customer_name,
            SUM(s.amount) as total_sales,
            COUNT(s.id) as transaction_count
        FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
        GROUP BY s.customer_name
        ORDER BY total_sales DESC
        LIMIT %s
    """, (business_id, start_date, end_date, limit))
    customers = cursor.fetchall()
    
    # Calculate total revenue for percentage
    cursor.execute("""
        SELECT SUM(amount) as total FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
    """, (business_id, start_date, end_date))
    total_revenue = float(cursor.fetchone()['total'] or 0)
    
    result = []
    for i, c in enumerate(customers):
        sales = float(c['total_sales'] or 0)
        result.append({
            'rank': i + 1,
            'name': c['customer_name'],
            'total_sales': sales,
            'percentage': round((sales / total_revenue * 100), 1) if total_revenue > 0 else 0,
            'transaction_count': c['transaction_count']
        })
    
    cursor.close()
    db.close()
    
    return jsonify({
        'customers': result,
        'total_revenue': total_revenue,
        'period': period
    })


@insights_bp.route('/api/sales-by-day')
def sales_by_day():
    """Get sales grouped by day of week"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT 
            DAYOFWEEK(s.sale_date) as day_num,
            DAYNAME(s.sale_date) as day_name,
            SUM(s.amount) as total_sales,
            COUNT(s.id) as transaction_count,
            AVG(s.amount) as avg_sale
        FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.sale_date >= DATE_SUB(NOW(), INTERVAL 90 DAY)
        GROUP BY DAYOFWEEK(s.sale_date), DAYNAME(s.sale_date)
        ORDER BY day_num
    """, (business_id,))
    results = cursor.fetchall()
    
    # Order: Sunday(1) to Saturday(7)
    day_order = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    
    sales_by_day = {}
    for day in day_order:
        sales_by_day[day] = 0
    
    for row in results:
        sales_by_day[row['day_name']] = float(row['total_sales'] or 0)
    
    cursor.close()
    db.close()
    
    return jsonify({
        'sales_by_day': sales_by_day,
        'days': day_order
    })


@insights_bp.route('/api/saved-scenarios', methods=['GET', 'POST'])
def saved_scenarios():
    """Get or save predictive planner scenarios"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        # Save a new scenario
        data = request.get_json()
        name = data.get('name')
        scenario_type = data.get('scenario_type', 'general')
        product_id = data.get('product_id')
        scenario_data = data.get('data')
        
        cursor.execute("""
            INSERT INTO saved_scenarios (user_id, name, scenario_type, product_id, data)
            VALUES (%s, %s, %s, %s, %s)
        """, (session['user_id'], name, scenario_type, product_id, json.dumps(scenario_data)))
        db.commit()
        
        return jsonify({'success': True, 'id': cursor.lastrowid})
    
    else:
        # Get saved scenarios
        cursor.execute("""
            SELECT id, name, scenario_type, product_id, data, created_at
            FROM saved_scenarios
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (session['user_id'],))
        scenarios = cursor.fetchall()
        
        for s in scenarios:
            s['data'] = json.loads(s['data']) if s['data'] else {}
        
        cursor.close()
        db.close()
        
        return jsonify({'scenarios': scenarios})


@insights_bp.route('/api/delete-scenario/<int:scenario_id>', methods=['DELETE'])
def delete_scenario(scenario_id):
    """Delete a saved scenario"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("DELETE FROM saved_scenarios WHERE id = %s AND user_id = %s", 
                   (scenario_id, session['user_id']))
    db.commit()
    
    cursor.close()
    db.close()
    
    return jsonify({'success': True})


@insights_bp.route('/api/calculate-scenario', methods=['POST'])
def calculate_scenario():
    """Calculate projected numbers for a custom scenario (no save)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    scenario_type = data.get('scenario_type', 'general')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    # Get current baseline
    cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN t.type = 'income' THEN t.amount ELSE 0 END), 0) as total_income,
            COALESCE(SUM(CASE WHEN t.type = 'expense' THEN t.amount ELSE 0 END), 0) as total_expense
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s
    """, (business_id,))
    baseline = cursor.fetchone()
    
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total_sales FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s
    """, (business_id,))
    sales = cursor.fetchone()
    
    current_revenue = baseline['total_income'] + sales['total_sales']
    current_expenses = baseline['total_expense']
    current_profit = current_revenue - current_expenses
    
    if scenario_type == 'general':
        price_change = float(data.get('price_change', 0)) / 100
        volume_change = float(data.get('volume_change', 0)) / 100
        expense_change = float(data.get('expense_change', 0)) / 100
        
        new_revenue = current_revenue * (1 + price_change) * (1 + volume_change)
        new_expenses = current_expenses * (1 + expense_change)
        new_profit = new_revenue - new_expenses
        
        result = {
            'current_revenue': current_revenue,
            'current_expenses': current_expenses,
            'current_profit': current_profit,
            'new_revenue': new_revenue,
            'new_expenses': new_expenses,
            'new_profit': new_profit,
            'profit_change': new_profit - current_profit,
            'profit_change_percent': ((new_profit - current_profit) / current_profit * 100) if current_profit != 0 else 0
        }
        
    elif scenario_type == 'product':
        product_id = data.get('product_id')
        new_price = float(data.get('new_price', 0))
        new_volume = float(data.get('new_volume', 0))
        
        if product_id:
            cursor.execute("""
                SELECT name, price, cogs, SUM(amount) as total_sales, COUNT(*) as units_sold
                FROM products p
                LEFT JOIN sales s ON s.description LIKE CONCAT('%', p.name, '%')
                WHERE p.id = %s
                GROUP BY p.id
            """, (product_id,))
            product = cursor.fetchone()
            
            if product:
                old_revenue = float(product['total_sales'] or 0)
                new_product_revenue = new_price * new_volume
                revenue_change = new_product_revenue - old_revenue
                
                new_total_revenue = current_revenue + revenue_change
                new_profit = new_total_revenue - current_expenses
                
                result = {
                    'current_revenue': current_revenue,
                    'current_profit': current_profit,
                    'new_revenue': new_total_revenue,
                    'new_profit': new_profit,
                    'product_old_revenue': old_revenue,
                    'product_new_revenue': new_product_revenue,
                    'revenue_change': revenue_change,
                    'profit_change': new_profit - current_profit
                }
            else:
                result = {'error': 'Product not found'}
        else:
            result = {'error': 'Product ID required'}
    else:
        result = {'error': 'Invalid scenario type'}
    
    cursor.close()
    db.close()
    
    return jsonify(result)

@insights_bp.route('/api/yoy-comparison')
def yoy_comparison():
    """Year-over-year comparison"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    today = date.today()
    
    # This month this year
    this_year_start = today.replace(day=1)
    this_year_end = today
    
    # This month last year
    last_year_start = this_year_start.replace(year=this_year_start.year - 1)
    last_year_end = this_year_end.replace(year=this_year_end.year - 1)
    
    # Get current year revenue (sales + income) filtered by business_id
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as revenue FROM (
            SELECT s.amount FROM sales s
            JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
            UNION ALL
            SELECT t.amount FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date BETWEEN %s AND %s
        ) as all_revenue
    """, (business_id, this_year_start, this_year_end, business_id, this_year_start, this_year_end))
    current_revenue = float(cursor.fetchone()['revenue'] or 0)
    
    # Get last year revenue filtered by business_id
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as revenue FROM (
            SELECT s.amount FROM sales s
            JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
            UNION ALL
            SELECT t.amount FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date BETWEEN %s AND %s
        ) as all_revenue
    """, (business_id, last_year_start, last_year_end, business_id, last_year_start, last_year_end))
    last_revenue = float(cursor.fetchone()['revenue'] or 0)
    
    # Get current year expenses filtered by business_id
    cursor.execute("""
        SELECT COALESCE(SUM(t.amount), 0) as expenses
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, this_year_start, this_year_end))
    current_expenses = float(cursor.fetchone()['expenses'] or 0)
    
    # Get last year expenses filtered by business_id
    cursor.execute("""
        SELECT COALESCE(SUM(t.amount), 0) as expenses
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, last_year_start, last_year_end))
    last_expenses = float(cursor.fetchone()['expenses'] or 0)
    
    current_profit = current_revenue - current_expenses
    last_profit = last_revenue - last_expenses
    
    revenue_change = ((current_revenue - last_revenue) / last_revenue * 100) if last_revenue > 0 else 0
    expense_change = ((current_expenses - last_expenses) / last_expenses * 100) if last_expenses > 0 else 0
    profit_change = ((current_profit - last_profit) / last_profit * 100) if last_profit > 0 else 0
    
    cursor.close()
    db.close()
    
    return jsonify({
        'current': {
            'revenue': current_revenue,
            'expenses': current_expenses,
            'profit': current_profit
        },
        'previous': {
            'revenue': last_revenue,
            'expenses': last_expenses,
            'profit': last_profit
        },
        'changes': {
            'revenue': round(revenue_change, 1),
            'expenses': round(expense_change, 1),
            'profit': round(profit_change, 1)
        }
    })

@insights_bp.route('/api/product-list')
def product_list():
    """Get list of products for predictive planner dropdown"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Use business_id to get products from all users in this business
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT p.id, p.name, p.price, p.cogs
        FROM products p
        JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.deleted_at IS NULL
        ORDER BY p.name ASC
    """, (business_id,))
    
    products = cursor.fetchall()
    
    # If no products found by business_id, fall back to user_id
    if not products:
        cursor.execute("""
            SELECT p.id, p.name, p.price, p.cogs
            FROM products p
            WHERE p.user_id = %s AND p.deleted_at IS NULL
            ORDER BY p.name ASC
        """, (session['user_id'],))
        products = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    # Convert decimals to float for JSON
    for p in products:
        p['price'] = float(p['price']) if p['price'] else 0
        p['cogs'] = float(p['cogs']) if p['cogs'] else 0
    
    return jsonify({'products': products})

@insights_bp.route('/api/sales-by-week')
def sales_by_week():
    """Get sales grouped by week of current month"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    today = date.today()
    first_of_month = today.replace(day=1)
    
    # Get all sales this month
    cursor.execute("""
        SELECT 
            s.sale_date,
            s.amount
        FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.sale_date >= %s AND s.sale_date <= %s
        ORDER BY s.sale_date ASC
    """, (business_id, first_of_month, today))
    sales = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    # Group by week (Week 1: days 1-7, Week 2: days 8-14, etc.)
    weeks = {'Week 1': 0, 'Week 2': 0, 'Week 3': 0, 'Week 4': 0, 'Week 5': 0}
    week_counts = {'Week 1': 0, 'Week 2': 0, 'Week 3': 0, 'Week 4': 0, 'Week 5': 0}
    
    for s in sales:
        day = s['sale_date'].day
        amount = float(s['amount'] or 0)
        
        if day <= 7:
            weeks['Week 1'] += amount
            week_counts['Week 1'] += 1
        elif day <= 14:
            weeks['Week 2'] += amount
            week_counts['Week 2'] += 1
        elif day <= 21:
            weeks['Week 3'] += amount
            week_counts['Week 3'] += 1
        elif day <= 28:
            weeks['Week 4'] += amount
            week_counts['Week 4'] += 1
        else:
            weeks['Week 5'] += amount
            week_counts['Week 5'] += 1
    
    # Calculate total for percentages
    total_month = sum(weeks.values())
    
    # Build response (only include weeks that exist)
    week_order = ['Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5']
    result = []
    for week_name in week_order:
        if total_month > 0 or weeks[week_name] > 0:  # Show week if it has data or it's the first week with no data yet
            result.append({
                'week_label': week_name,
                'total_sales': round(weeks[week_name], 2),
                'transaction_count': week_counts[week_name],
                'percent_of_month': round((weeks[week_name] / total_month * 100), 1) if total_month > 0 else 0
            })
    
    return jsonify({
        'weeks': result,
        'total_month': round(total_month, 2),
        'month': first_of_month.strftime('%B %Y')
    })


@insights_bp.route('/api/product-baseline/<int:product_id>')
def product_baseline(product_id):
    """Get baseline numbers for a specific product (for predictive planner)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get product details
    cursor.execute("""
        SELECT p.id, p.name, p.price, p.cogs
        FROM products p
        JOIN users u ON p.user_id = u.id
        WHERE p.id = %s AND u.business_id = %s AND p.deleted_at IS NULL
    """, (product_id, business_id))
    product = cursor.fetchone()
    
    if not product:
        cursor.close()
        db.close()
        return jsonify({'error': 'Product not found'}), 404
    
    # Get sales for this product
    cursor.execute("""
        SELECT 
            COALESCE(SUM(s.amount), 0) as total_sales,
            COUNT(s.id) as units_sold
        FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.description LIKE CONCAT('%%', %s, '%%')
    """, (business_id, product['name']))
    sales_data = cursor.fetchone()
    
    cursor.close()
    db.close()
    
    revenue = float(sales_data['total_sales'] or 0)
    units_sold = int(sales_data['units_sold'] or 0)
    price = float(product['price'] or 0)
    cogs = float(product['cogs'] or 0)
    profit = revenue - (cogs * units_sold)
    
    return jsonify({
        'product': {
            'id': product['id'],
            'name': product['name'],
            'price': price,
            'cogs': cogs,
            'revenue': revenue,
            'units_sold': units_sold,
            'profit': profit
        }
    })

# ========== EXISTING API ENDPOINTS (Keep as is) ==========

@insights_bp.route('/api/chart-data')
def chart_data():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    period = request.args.get('period', '7')
    days = int(period)
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    
    cursor.execute("""
        SELECT 
            t.transaction_date as date,
            SUM(CASE WHEN t.type = 'income' THEN t.amount ELSE 0 END) as sales,
            SUM(CASE WHEN t.type = 'expense' THEN t.amount ELSE 0 END) as expenses
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.transaction_date BETWEEN %s AND %s
        GROUP BY t.transaction_date
        ORDER BY t.transaction_date ASC
    """, (business_id, start_date, end_date))
    daily_data = cursor.fetchall()
    
    cursor.execute("""
        SELECT 
            COALESCE(t.category, 'Other') as category,
            SUM(t.amount) as total
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' 
        AND t.transaction_date BETWEEN %s AND %s
        GROUP BY t.category
        ORDER BY total DESC
        LIMIT 5
    """, (business_id, start_date, end_date))
    category_data = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    labels = [d['date'].strftime('%b %d') for d in daily_data]
    sales = [float(d['sales'] or 0) for d in daily_data]
    expenses = [float(d['expenses'] or 0) for d in daily_data]
    category_labels = [c['category'] for c in category_data]
    category_values = [float(c['total'] or 0) for c in category_data]
    
    return jsonify({
        'labels': labels,
        'sales': sales,
        'expenses': expenses,
        'categoryLabels': category_labels,
        'categoryValues': category_values,
        'period': days
    })


@insights_bp.route('/api/stats-detail/<stat_type>')
def stats_detail(stat_type):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    if stat_type == 'sales':
        cursor.execute("""
            SELECT s.id, s.customer_name as name, s.amount, s.sale_date as date, s.description, 'Sale' as source
            FROM sales s
            JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
            ORDER BY s.sale_date DESC
        """, (business_id, week_start, week_end))
        sales_items = cursor.fetchall()
        
        cursor.execute("""
            SELECT t.id, t.description as name, t.amount, t.transaction_date as date, '' as description, 'Other Income' as source
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' 
            AND t.transaction_date BETWEEN %s AND %s
            ORDER BY t.transaction_date DESC
        """, (business_id, week_start, week_end))
        income_items = cursor.fetchall()
        
        items = sales_items + income_items
        items.sort(key=lambda x: x['date'], reverse=True)
        title = "This Week's Revenue (Sales + Other Income)"
        
    elif stat_type == 'expenses':
        cursor.execute("""
            SELECT t.id, t.description, t.amount, t.transaction_date as date, t.category
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'expense' 
            AND t.transaction_date BETWEEN %s AND %s
            ORDER BY t.transaction_date DESC
        """, (business_id, week_start, week_end))
        items = cursor.fetchall()
        title = "This Week's Expenses"
        
    elif stat_type == 'profit':
        cursor.execute("""
            SELECT t.id, t.description, t.amount, t.transaction_date as date, 
                   CASE WHEN t.type = 'income' THEN 'Income' ELSE 'Expense' END as type
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.transaction_date BETWEEN %s AND %s
            ORDER BY t.transaction_date DESC
        """, (business_id, week_start, week_end))
        items = cursor.fetchall()
        title = "This Week's Transactions"
    else:
        items = []
        title = "Details"
    
    cursor.close()
    db.close()
    
    for item in items:
        if 'date' in item and hasattr(item['date'], 'isoformat'):
            item['date'] = item['date'].isoformat()
    
    return jsonify({'title': title, 'items': items})

# ═══════════════════════════════════════════
# SMART FEATURES — Anomaly Detection + Insights
# ═══════════════════════════════════════════

@insights_bp.route('/api/anomalies')
def api_anomalies():
    """Detect unusual spending patterns across categories."""
    if 'user_id' not in session:
        return jsonify([]), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    today = date.today()
    four_weeks_ago = today - timedelta(days=28)
    
    # Get this week's spending per category
    cursor.execute("""
        SELECT t.category, SUM(t.amount) as this_week
        FROM transactions t JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense'
          AND t.transaction_date >= %s AND t.deleted_at IS NULL
        GROUP BY t.category
    """, (business_id, four_weeks_ago + timedelta(days=21)))
    this_week = {row['category']: float(row['this_week'] or 0) for row in cursor.fetchall()}
    
    # Get 4-week average per category
    cursor.execute("""
        SELECT t.category, SUM(t.amount) / 4 as weekly_avg
        FROM transactions t JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense'
          AND t.transaction_date >= %s AND t.deleted_at IS NULL
        GROUP BY t.category
    """, (business_id, four_weeks_ago))
    averages = {row['category']: float(row['weekly_avg'] or 0) for row in cursor.fetchall()}
    
    anomalies = []
    for category, amount in this_week.items():
        avg = averages.get(category, 0)
        if avg > 0 and amount > avg * 2.5:
            anomalies.append({
                'category': category,
                'this_week': round(amount, 2),
                'average': round(avg, 2),
                'multiplier': round(amount / avg, 1),
                'severity': 'high' if amount > avg * 4 else 'medium'
            })
    
    cursor.close()
    db.close()
    return jsonify(sorted(anomalies, key=lambda x: x['multiplier'], reverse=True))


@insights_bp.route('/api/insights')
def api_insights():
    """Generate plain-language business insights."""
    if 'user_id' not in session:
        return jsonify([]), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    today = date.today()
    first_of_month = today.replace(day=1)
    last_month_start = (first_of_month - timedelta(days=1)).replace(day=1)
    insights = []
    
    # 1. Profit margin comparison
    cursor.execute("""
        SELECT SUM(amount) as total FROM (
            SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date >= %s
            UNION ALL
            SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date >= %s
        ) AS revenue
    """, (business_id, first_of_month, business_id, first_of_month))
    this_month_revenue = float(cursor.fetchone()['total'] or 0)
    
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date >= %s AND t.deleted_at IS NULL
    """, (business_id, first_of_month))
    this_month_expenses = float(cursor.fetchone()['total'] or 0)
    
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date >= %s 
        AND t.transaction_date < %s AND t.deleted_at IS NULL
    """, (business_id, last_month_start, first_of_month))
    last_month_expenses = float(cursor.fetchone()['total'] or 0)
    
    this_margin = (this_month_revenue - this_month_expenses) / this_month_revenue * 100 if this_month_revenue > 0 else 0
    last_month_revenue_query = cursor.execute("""
        SELECT SUM(amount) as total FROM (
            SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date >= %s AND t.transaction_date < %s
            UNION ALL
            SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date >= %s AND s.sale_date < %s
        ) AS revenue
    """, (business_id, last_month_start, first_of_month, business_id, last_month_start, first_of_month))
    last_month_revenue = float(cursor.fetchone()['total'] or 0)
    last_margin = (last_month_revenue - last_month_expenses) / last_month_revenue * 100 if last_month_revenue > 0 else 0
    
    if this_margin < last_margin - 5 and this_month_revenue > 0:
        insights.append({
            'type': 'margin_drop',
            'icon': 'fa-arrow-trend-down',
            'color': '#ef4444',
            'message': f'Your profit margin dropped from {last_margin:.0f}% to {this_margin:.0f}% this month.',
            'detail': 'Review your biggest expense categories for increases.'
        })
    elif this_margin > last_margin + 5:
        insights.append({
            'type': 'margin_gain',
            'icon': 'fa-arrow-trend-up',
            'color': '#10b981',
            'message': f'Your profit margin improved from {last_margin:.0f}% to {this_margin:.0f}% this month.',
            'detail': 'Whatever you are doing, keep doing it.'
        })
    
    # 2. Best sales day
    cursor.execute("""
        SELECT DAYNAME(sale_date) as day_name, AVG(daily_total) as avg_total
        FROM (
            SELECT sale_date, SUM(amount) as daily_total
            FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date >= %s AND s.deleted_at IS NULL
            GROUP BY sale_date
        ) AS daily GROUP BY DAYNAME(sale_date) ORDER BY avg_total DESC LIMIT 1
    """, (business_id, today - timedelta(days=90)))
    best_day = cursor.fetchone()
    
    if best_day:
        insights.append({
            'type': 'best_day',
            'icon': 'fa-calendar-star',
            'color': '#f59e0b',
            'message': f'{best_day["day_name"]}s are your best sales day — averaging ₱{float(best_day["avg_total"]):,.0f}.',
            'detail': 'Schedule promotions or restocks before this day.'
        })
    
    # 3. Overdue customers
    cursor.execute("""
        SELECT c.name, i.amount, i.due_date, 
               DATEDIFF(%s, i.due_date) as days_overdue,
               COALESCE(SUM(p.amount), 0) as paid
        FROM invoices i JOIN customers c ON i.customer_id = c.id
        JOIN users u ON i.user_id = u.id
        LEFT JOIN payments p ON i.id = p.invoice_id
        WHERE u.business_id = %s AND i.status IN ('unpaid', 'partially_paid')
          AND i.due_date < %s AND i.deleted_at IS NULL
        GROUP BY i.id ORDER BY days_overdue DESC LIMIT 3
    """, (today, business_id, today))
    overdue = cursor.fetchall()
    
    if overdue:
        names = [o['name'] for o in overdue]
        total_overdue = sum(float(o['amount'] - o['paid']) for o in overdue)
        insights.append({
            'type': 'collections',
            'icon': 'fa-exclamation-circle',
            'color': '#ef4444',
            'message': f'{len(overdue)} customer(s) with overdue payments: {", ".join(names[:2])}.',
            'detail': f'Total outstanding: ₱{total_overdue:,.0f}. Send payment reminders.'
        })
    
    # 4. Top product this month
    cursor.execute("""
        SELECT si.product_name, SUM(si.amount) as total
        FROM sale_items si JOIN sales s ON si.sale_id = s.id
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.sale_date >= %s AND s.deleted_at IS NULL
        GROUP BY si.product_name ORDER BY total DESC LIMIT 1
    """, (business_id, first_of_month))
    top_product = cursor.fetchone()
    
    if top_product:
        insights.append({
            'type': 'top_product',
            'icon': 'fa-star',
            'color': '#8b5cf6',
            'message': f'"{top_product["product_name"]}" is your best seller this month — ₱{float(top_product["total"]):,.0f} in sales.',
            'detail': 'Make sure this item is always in stock.'
        })
    
    # 5. Low stock warning
    cursor.execute("""
        SELECT COUNT(*) as count FROM products p JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.quantity < p.reorder_level AND p.deleted_at IS NULL
    """, (business_id,))
    low_stock = cursor.fetchone()
    
    if low_stock and low_stock['count'] > 0:
        insights.append({
            'type': 'low_stock',
            'icon': 'fa-box-open',
            'color': '#f59e0b',
            'message': f'{low_stock["count"]} product(s) are running low on stock.',
            'detail': 'Create purchase orders before you run out.'
        })
    
    cursor.close()
    db.close()
    return jsonify(insights)


# ═══════════════════════════════════════════
# SCRATCHPAD / SMART ENTRY PARSER
# ═══════════════════════════════════════════

@insights_bp.route('/api/parse_scratchpad', methods=['POST'])
def parse_scratchpad():
    """Parse natural language into transaction preview."""
    if 'user_id' not in session:
        return jsonify([]), 401
    
    import re
    from datetime import date, timedelta
    
    text = request.get_json().get('text', '').strip()
    if not text:
        return jsonify([])
    
    text_lower = text.lower()
    today = date.today()
    entries = []
    
    # Date detection
    detected_date = today
    if 'yesterday' in text_lower:
        detected_date = today - timedelta(days=1)
    elif 'today' in text_lower:
        detected_date = today
    elif 'last monday' in text_lower:
        days_since_monday = today.weekday()
        detected_date = today - timedelta(days=days_since_monday + 7)
    elif 'last sunday' in text_lower:
        days_since_sunday = today.weekday() + 1 if today.weekday() < 6 else 0
        detected_date = today - timedelta(days=days_since_sunday + 7)
    
    # Try month-day pattern: "May 4", "jan 15"
    month_match = re.search(r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})', text_lower)
    if month_match:
        months = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
        m = month_match.group(1)[:3]
        d = int(month_match.group(2))
        detected_date = date(today.year, months[m], d)
        if detected_date > today:
            detected_date = date(today.year - 1, months[m], d)
    
    # Pattern 1: "sold X Y at Z each" or "sold X Y for Z each"
    sale_match = re.search(r'sold\s+(\d+)\s+(.+?)\s+(?:at|for)\s+([\d,.]+)\s*(?:each)?', text_lower)
    if sale_match:
        qty = int(sale_match.group(1))
        item = sale_match.group(2).strip().title()
        price = float(sale_match.group(3).replace(',', ''))
        entries.append({
            'date': str(detected_date),
            'type': 'sale',
            'description': item,
            'quantity': qty,
            'unit_price': price,
            'total': qty * price
        })
    
    # Pattern 2: "bought X Y for Z"
    expense_match = re.search(r'bought\s+(.+?)\s+for\s+([\d,.]+)', text_lower)
    if expense_match and not entries:
        item = expense_match.group(1).strip().title()
        amount = float(expense_match.group(2).replace(',', ''))
        entries.append({
            'date': str(detected_date),
            'type': 'expense',
            'description': item,
            'quantity': 1,
            'unit_price': amount,
            'total': amount
        })
    
    # Pattern 3: "paid Z for X"
    paid_match = re.search(r'paid\s+([\d,.]+)\s+for\s+(.+)', text_lower)
    if paid_match and not entries:
        amount = float(paid_match.group(1).replace(',', ''))
        item = paid_match.group(2).strip().title()
        entries.append({
            'date': str(detected_date),
            'type': 'expense',
            'description': item,
            'quantity': 1,
            'unit_price': amount,
            'total': amount
        })
    
    # Pattern 4: "received Z from [name]"
    received_match = re.search(r'received\s+([\d,.]+)\s+from\s+(.+)', text_lower)
    if received_match and not entries:
        amount = float(received_match.group(1).replace(',', ''))
        name = received_match.group(2).strip().title()
        entries.append({
            'date': str(detected_date),
            'type': 'income',
            'description': f'Payment from {name}',
            'quantity': 1,
            'unit_price': amount,
            'total': amount
        })
    
    # Pattern 5: "spent Z on X"
    spent_match = re.search(r'spent\s+([\d,.]+)\s+on\s+(.+)', text_lower)
    if spent_match and not entries:
        amount = float(spent_match.group(1).replace(',', ''))
        item = spent_match.group(2).strip().title()
        entries.append({
            'date': str(detected_date),
            'type': 'expense',
            'description': item,
            'quantity': 1,
            'unit_price': amount,
            'total': amount
        })
    
    # If no patterns matched, try to extract any amount and description
    if not entries:
        numbers = re.findall(r'([\d,.]+)', text)
        if numbers:
            amount = float(numbers[0].replace(',', ''))
            desc = text
            for n in numbers:
                desc = desc.replace(n, '')
            desc = desc.strip().title() or 'Entry'
            t = 'income' if amount > 0 else 'expense'
            entries.append({
                'date': str(detected_date),
                'type': t,
                'description': desc,
                'quantity': 1,
                'unit_price': abs(amount),
                'total': abs(amount)
            })
    
    return jsonify(entries)
