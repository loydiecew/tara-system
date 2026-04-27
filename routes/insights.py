from flask import Blueprint, render_template, session, redirect, url_for, jsonify, request
from datetime import date, timedelta
from models.database import get_db
from models.helpers import get_week_range

insights_bp = Blueprint('insights', __name__)

@insights_bp.route('/insights')
def insights():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get current date and week ranges
    today = date.today()
    current_week_start, current_week_end = get_week_range(today)
    last_week_start = current_week_start - timedelta(days=7)
    last_week_end = current_week_end - timedelta(days=7)
    
    # ========== CURRENT WEEK - SALES REVENUE ==========
    cursor.execute("""
        SELECT SUM(s.amount) as total FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
    """, (business_id, current_week_start, current_week_end))
    result = cursor.fetchone()
    current_sales_revenue = float(result['total']) if result['total'] else 0.0
    
    # ========== CURRENT WEEK - OTHER INCOME (from transactions) ==========
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'income' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, current_week_start, current_week_end))
    result = cursor.fetchone()
    current_other_income = float(result['total']) if result['total'] else 0.0
    
    # ========== TOTAL CURRENT WEEK INCOME ==========
    current_total_income = current_sales_revenue + current_other_income
    
    # ========== LAST WEEK - SALES REVENUE ==========
    cursor.execute("""
        SELECT SUM(s.amount) as total FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
    """, (business_id, last_week_start, last_week_end))
    result = cursor.fetchone()
    last_sales_revenue = float(result['total']) if result['total'] else 0.0
    
    # ========== LAST WEEK - OTHER INCOME (from transactions) ==========
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'income' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, last_week_start, last_week_end))
    result = cursor.fetchone()
    last_other_income = float(result['total']) if result['total'] else 0.0
    
    # ========== TOTAL LAST WEEK INCOME ==========
    last_total_income = last_sales_revenue + last_other_income
    
    # ========== CURRENT WEEK EXPENSES ==========
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, current_week_start, current_week_end))
    result = cursor.fetchone()
    current_expenses = float(result['total']) if result['total'] else 0.0
    
    # ========== LAST WEEK EXPENSES ==========
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, last_week_start, last_week_end))
    result = cursor.fetchone()
    last_expenses = float(result['total']) if result['total'] else 0.0
    
    # ========== PROFIT CALCULATIONS (Income - Expenses) ==========
    current_profit = current_total_income - current_expenses
    last_profit = last_total_income - last_expenses
    
    # ========== CURRENT WEEK EXPENSES BY CATEGORY ==========
    cursor.execute("""
        SELECT t.category, SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' 
        AND t.transaction_date BETWEEN %s AND %s
        GROUP BY t.category
    """, (business_id, current_week_start, current_week_end))
    current_expenses_by_category = {}
    for row in cursor.fetchall():
        if row['category']:
            current_expenses_by_category[row['category']] = float(row['total'])
    
    # ========== LAST WEEK EXPENSES BY CATEGORY ==========
    cursor.execute("""
        SELECT t.category, SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' 
        AND t.transaction_date BETWEEN %s AND %s
        GROUP BY t.category
    """, (business_id, last_week_start, last_week_end))
    last_expenses_by_category = {}
    for row in cursor.fetchall():
        if row['category']:
            last_expenses_by_category[row['category']] = float(row['total'])
    
    # ========== HELPER FUNCTION FOR PERCENTAGE CHANGE ==========
    def calc_change(current, last):
        if last == 0:
            return 0.0 if current == 0 else 100.0
        return ((current - last) / last) * 100.0
    
    # Calculate changes based on TOTAL income (not just sales)
    sales_change = calc_change(current_total_income, last_total_income)
    expense_change = calc_change(current_expenses, last_expenses)
    profit_change = calc_change(current_profit, last_profit)
    
    # Profit margin = Profit / Total Income * 100
    profit_margin = (current_profit / current_total_income * 100.0) if current_total_income > 0 else 0.0
    
    # ========== SMART ALERTS ==========
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
    
    # Alert 2: Sales/Income drop (>10% decrease)
    if last_total_income > 0 and sales_change < -10:
        alerts.append({
            'type': 'sales_drop',
            'severity': 'medium',
            'current': current_total_income,
            'last': last_total_income,
            'drop_pct': -sales_change,
            'message': f"Income dropped by {-sales_change:.0f}% this week"
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
    
    # ========== RECOMMENDATIONS ==========
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
                'action': f"Investigate why income dropped by {alert['drop_pct']:.0f}%. Consider a promotion.",
                'potential_gain': alert['last'] * 0.1,
                'message': f"A 10% income increase would add ₱{alert['last'] * 0.1:,.0f}"
            })
        elif alert['type'] == 'profit_decline':
            recommendations.append({
                'type': 'profit_improvement',
                'decline_pct': alert['decline_pct'],
                'action': f"Review both income and expenses. Profit dropped {alert['decline_pct']:.0f}%.",
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
    
    # ========== PREDICTIVE PLANNER ==========
    baseline_sales = float(current_total_income) if current_total_income > 0 else 100000.0
    baseline_expenses = float(current_expenses) if current_expenses > 0 else 70000.0
    baseline_profit = float(current_profit)
    
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
                         current_sales=current_total_income,
                         current_expenses=current_expenses,
                         current_profit=current_profit,
                         last_sales=last_total_income,
                         last_expenses=last_expenses,
                         last_profit=last_profit,
                         sales_change=sales_change,
                         expense_change=expense_change,
                         profit_change=profit_change,
                         profit_margin=profit_margin,
                         alerts=alerts,
                         recommendations=recommendations,
                         baseline_sales=baseline_sales,
                         baseline_expenses=baseline_expenses,
                         current_profit_baseline=baseline_profit,
                         scenarios=scenarios)

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
    
    # Daily sales and expenses for the business
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
    
    # Expense categories for the business
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
        # Get sales from sales table
        cursor.execute("""
            SELECT s.id, s.customer_name as name, s.amount, s.sale_date as date, s.description, 'Sale' as source
            FROM sales s
            JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
            ORDER BY s.sale_date DESC
        """, (business_id, week_start, week_end))
        sales_items = cursor.fetchall()
        
        # Get other income from transactions
        cursor.execute("""
            SELECT t.id, t.description as name, t.amount, t.transaction_date as date, '' as description, 'Other Income' as source
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' 
            AND t.transaction_date BETWEEN %s AND %s
            ORDER BY t.transaction_date DESC
        """, (business_id, week_start, week_end))
        income_items = cursor.fetchall()
        
        # Combine both
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
    
    # Convert date objects to string for JSON
    for item in items:
        if 'date' in item and hasattr(item['date'], 'isoformat'):
            item['date'] = item['date'].isoformat()
    
    return jsonify({'title': title, 'items': items})