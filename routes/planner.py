from flask import Blueprint, render_template, session, redirect, url_for, jsonify, request
from datetime import date
import json
from models.database import get_db

planner_bp = Blueprint('planner', __name__)

@planner_bp.route('/planner')
def planner():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    today = date.today()
    first_of_month = today.replace(day=1)
    
    # Current month actuals
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total FROM (
            SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date >= %s AND t.status != 'void'
            UNION ALL
            SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date >= %s
        ) AS revenue
    """, (business_id, first_of_month, business_id, first_of_month))
    current_revenue = float(cursor.fetchone()['total'] or 0)
    
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total FROM transactions t JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date >= %s AND t.status != 'void'
    """, (business_id, first_of_month))
    current_expenses = float(cursor.fetchone()['total'] or 0)
    current_profit = current_revenue - current_expenses
    
    # Products for per-product mode
    cursor.execute("""
        SELECT p.id, p.name, p.price, p.cogs FROM products p JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.deleted_at IS NULL ORDER BY p.name
    """, (business_id,))
    products = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('planner.html',
                         username=session['username'],
                         current_revenue=current_revenue,
                         current_expenses=current_expenses,
                         current_profit=current_profit,
                         products=products)


@planner_bp.route('/api/planner/actuals')
def planner_actuals():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    first_of_month = date.today().replace(day=1)
    
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total FROM (
            SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date >= %s AND t.status != 'void'
            UNION ALL
            SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date >= %s
        ) AS revenue
    """, (business_id, first_of_month, business_id, first_of_month))
    revenue = float(cursor.fetchone()['total'] or 0)
    
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total FROM transactions t JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date >= %s AND t.status != 'void'
    """, (business_id, first_of_month))
    expenses = float(cursor.fetchone()['total'] or 0)
    
    cursor.close()
    db.close()
    
    return jsonify({'revenue': revenue, 'expenses': expenses, 'profit': revenue - expenses})


@planner_bp.route('/api/planner/breakeven', methods=['POST'])
def breakeven():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    fixed_costs = float(data.get('fixed_costs', 0))
    price_per_unit = float(data.get('price_per_unit', 0))
    variable_cost_per_unit = float(data.get('variable_cost_per_unit', 0))
    
    if price_per_unit <= variable_cost_per_unit:
        return jsonify({'error': 'Price must exceed variable cost per unit'}), 400
    
    contribution_margin = price_per_unit - variable_cost_per_unit
    breakeven_units = fixed_costs / contribution_margin if contribution_margin > 0 else 0
    breakeven_revenue = breakeven_units * price_per_unit
    
    return jsonify({
        'breakeven_units': round(breakeven_units, 0),
        'breakeven_revenue': round(breakeven_revenue, 2),
        'contribution_margin': round(contribution_margin, 2)
    })


@planner_bp.route('/api/saved-scenarios', methods=['GET', 'POST'])
def saved_scenarios():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        data = request.get_json()
        name = data.get('name')
        scenario_type = data.get('scenario_type', 'general')
        product_id = data.get('product_id')
        scenario_data = data.get('data')
        notes = data.get('notes', '')
        
        cursor.execute("""
            INSERT INTO saved_scenarios (user_id, name, scenario_type, product_id, data, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (session['user_id'], name, scenario_type, product_id, json.dumps(scenario_data), notes))
        db.commit()
        return jsonify({'success': True, 'id': cursor.lastrowid})
    else:
        cursor.execute("""
            SELECT id, name, scenario_type, product_id, data, notes, created_at
            FROM saved_scenarios WHERE user_id = %s ORDER BY created_at DESC
        """, (session['user_id'],))
        scenarios = cursor.fetchall()
        for s in scenarios:
            s['data'] = json.loads(s['data']) if isinstance(s['data'], str) else (s['data'] or {})
        cursor.close()
        db.close()
        return jsonify({'scenarios': scenarios})


@planner_bp.route('/api/delete-scenario/<int:scenario_id>', methods=['DELETE'])
def delete_scenario(scenario_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM saved_scenarios WHERE id = %s AND user_id = %s", (scenario_id, session['user_id']))
    db.commit()
    cursor.close()
    db.close()
    return jsonify({'success': True})