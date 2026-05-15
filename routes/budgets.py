from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from datetime import date, timedelta
from models.database import get_db

budgets_bp = Blueprint('budgets', __name__)

# Pre-defined expense categories that always show
DEFAULT_CATEGORIES = [
    'Supplies', 'Rent', 'Utilities', 'Salary', 'Transport',
    'Marketing', 'Inventory', 'Equipment', 'Maintenance', 'Other'
]

@budgets_bp.route('/budgets')
def budgets():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    if session.get('plan') not in ['professional', 'suite']:
        flash('Budgeting is available on Professional and Suite plans.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    today = date.today()
    current_month = today.replace(day=1).isoformat()
    
    # Get all budgets with actual spending
    cursor.execute("""
        SELECT 
            b.id, b.category, b.month, b.budget_amount, b.approval_threshold,
            COALESCE(SUM(t.amount), 0) as actual_amount
        FROM budgets b
        JOIN users u ON b.user_id = u.id
        LEFT JOIN transactions t ON t.category = b.category 
            AND MONTH(t.transaction_date) = MONTH(b.month)
            AND YEAR(t.transaction_date) = YEAR(b.month)
            AND t.type = 'expense'
            AND t.status = 'active'
            AND t.deleted_at IS NULL
            AND t.user_id = b.user_id
        WHERE b.deleted_at IS NULL AND u.business_id = %s
        GROUP BY b.id, b.category, b.month, b.budget_amount, b.approval_threshold
        ORDER BY b.month DESC, b.category ASC
    """, (business_id,))
    budgets = cursor.fetchall()
    
    for b in budgets:
        b['variance'] = float(b['budget_amount']) - float(b['actual_amount'])
        b['percent_used'] = round((float(b['actual_amount']) / float(b['budget_amount'])) * 100, 1) if float(b['budget_amount']) > 0 else 0
        b['over_budget'] = float(b['actual_amount']) > float(b['budget_amount'])
    
    # Get custom categories from existing transactions + defaults
    cursor.execute("""
        SELECT DISTINCT category FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.category IS NOT NULL
        AND t.category != ''
        ORDER BY category
    """, (business_id,))
    custom_cats = [row['category'] for row in cursor.fetchall()]
    
    # Merge defaults + custom, no duplicates
    categories = list(dict.fromkeys(DEFAULT_CATEGORIES + custom_cats))
    
    cursor.close()
    db.close()
    
    # Get unique months for dropdown
    unique_months = []
    seen = set()
    for b in budgets:
        m = b['month'].strftime('%Y-%m') if hasattr(b['month'], 'strftime') else str(b['month'])[:7]
        if m not in seen:
            unique_months.append({'month': b['month'], 'label': b['month'].strftime('%B %Y') if hasattr(b['month'], 'strftime') else m})
            seen.add(m)
    
    return render_template('budgets.html',
                         budgets=budgets,
                         categories=categories,
                         unique_months=unique_months,
                         current_month=current_month,
                         today=today.isoformat())


@budgets_bp.route('/set_budget', methods=['POST'])
def set_budget():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    category = request.form['category']
    month = request.form['month']
    if len(month) == 7:
        month = month + '-01'
    budget_amount = float(request.form['budget_amount'])
    threshold = request.form.get('approval_threshold', '').strip()
    approval_threshold = float(threshold) if threshold else None

    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        INSERT INTO budgets (user_id, category, month, budget_amount, approval_threshold)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE budget_amount = VALUES(budget_amount), 
                                approval_threshold = VALUES(approval_threshold)
    """, (session['user_id'], category, month, budget_amount, approval_threshold))
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Budget set: {category} — ₱{budget_amount:,.2f}', 'success')
    return redirect(url_for('budgets.budgets'))


@budgets_bp.route('/delete_budget/<int:budget_id>')
def delete_budget(budget_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE budgets SET deleted_at = NOW() WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                   (budget_id, session['user_id']))
    db.commit()
    cursor.close()
    db.close()
    
    flash('Budget removed.', 'success')
    return redirect(url_for('budgets.budgets'))


@budgets_bp.route('/api/budget-comparison')
def budget_comparison():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    month = request.args.get('month', date.today().replace(day=1).isoformat())
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT 
            b.category, b.budget_amount,
            COALESCE(SUM(t.amount), 0) as actual_amount
        FROM budgets b
        JOIN users u ON b.user_id = u.id
        LEFT JOIN transactions t ON t.category = b.category 
            AND MONTH(t.transaction_date) = MONTH(b.month)
            AND YEAR(t.transaction_date) = YEAR(b.month)
            AND t.type = 'expense'
            AND t.status = 'active'
            AND t.deleted_at IS NULL
            AND t.user_id = b.user_id
        WHERE u.business_id = %s AND b.month = %s AND b.deleted_at IS NULL
        GROUP BY b.category, b.budget_amount
        ORDER BY b.category
    """, (business_id, month))
    data = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return jsonify({
        'categories': [d['category'] for d in data],
        'budget': [float(d['budget_amount']) for d in data],
        'actual': [float(d['actual_amount']) for d in data]
    })