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
    
    # ========== CURRENT WEEK - OTHER INCOME ==========
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'income' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, current_week_start, current_week_end))
    result = cursor.fetchone()
    current_other_income = float(result['total']) if result['total'] else 0.0
    
    current_total_income = current_sales_revenue + current_other_income
    
    # ========== LAST WEEK - SALES REVENUE ==========
    cursor.execute("""
        SELECT SUM(s.amount) as total FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
    """, (business_id, last_week_start, last_week_end))
    result = cursor.fetchone()
    last_sales_revenue = float(result['total']) if result['total'] else 0.0
    
    # ========== LAST WEEK - OTHER INCOME ==========
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'income' 
        AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, last_week_start, last_week_end))
    result = cursor.fetchone()
    last_other_income = float(result['total']) if result['total'] else 0.0
    
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
    
    current_profit = current_total_income - current_expenses
    last_profit = last_total_income - last_expenses
    
    # ========== EXPENSES BY CATEGORY ==========
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
    
    # ========== PERCENTAGE CHANGES ==========
    def calc_change(current, last):
        if last == 0:
            return 0.0 if current == 0 else 100.0
        return ((current - last) / last) * 100.0
    
    sales_change = calc_change(current_total_income, last_total_income)
    expense_change = calc_change(current_expenses, last_expenses)
    profit_change = calc_change(current_profit, last_profit)
    profit_margin = (current_profit / current_total_income * 100.0) if current_total_income > 0 else 0.0
    
    # ========== SMART ALERTS ==========
    alerts = []
    
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
    
    if last_total_income > 0 and sales_change < -10:
        alerts.append({
            'type': 'sales_drop',
            'severity': 'medium',
            'current': current_total_income,
            'last': last_total_income,
            'drop_pct': -sales_change,
            'message': f"Income dropped by {-sales_change:.0f}% this week"
        })
    
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
    
    # ========== PREDICTIVE PLANNER BASELINE ==========
    baseline_sales = float(current_total_income) if current_total_income > 0 else 100000.0
    baseline_expenses = float(current_expenses) if current_expenses > 0 else 70000.0
    baseline_profit = float(current_profit)
    
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
                         current_profit_baseline=baseline_profit)


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