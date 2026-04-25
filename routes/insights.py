from flask import Blueprint, render_template, session, redirect, url_for
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
    baseline_sales = float(current_sales) if current_sales > 0 else 100000.0
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
                         alerts=alerts,
                         recommendations=recommendations,
                         baseline_sales=baseline_sales,
                         baseline_expenses=baseline_expenses,
                         current_profit_baseline=baseline_profit,
                         scenarios=scenarios)