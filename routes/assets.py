from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from models.database import get_db
from models.access_control import check_module_access

assets_bp = Blueprint('assets', __name__)

@assets_bp.route('/assets')
def assets():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    if not check_module_access('assets'): return redirect(url_for('dashboard.dashboard'))

    if session.get('plan') not in ['suite']:
        flash('Fixed Assets are available on Enterprise plan only.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT a.* FROM assets a
        JOIN users u ON a.user_id = u.id
        WHERE a.deleted_at IS NULL AND u.business_id = %s
        ORDER BY a.purchase_date DESC
    """, (business_id,))
    assets = cursor.fetchall()
    
    # Auto-update depreciation for all active assets
    today = date.today()
    for a in assets:
        if a['status'] == 'active':
            months_elapsed = (today.year - a['purchase_date'].year) * 12 + (today.month - a['purchase_date'].month)
            if months_elapsed < 0:
                months_elapsed = 0
            a['months_elapsed'] = months_elapsed
            a['accumulated'] = a['monthly_depreciation'] * months_elapsed
            a['current_value'] = float(a['cost']) - a['accumulated']
            if a['current_value'] < float(a['salvage_value']):
                a['current_value'] = float(a['salvage_value'])
    
    total_cost = sum(float(a['cost'] or 0) for a in assets)
    total_value = sum(float(a['current_value'] or 0) for a in assets)
    total_depreciation = total_cost - total_value
    
    cursor.close()
    db.close()
    
    return render_template('assets.html',
                         username=session['username'],
                         assets=assets,
                         total_cost=total_cost,
                         total_value=total_value,
                         total_depreciation=total_depreciation,
                         today=date.today().isoformat())


@assets_bp.route('/add_asset', methods=['POST'])
def add_asset():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    name = request.form['name']
    category = request.form.get('category', '')
    purchase_date = request.form['purchase_date']
    cost = float(request.form['cost'])
    useful_life_months = int(request.form['useful_life_months'])
    salvage_value = float(request.form.get('salvage_value', 0))
    
    monthly_depreciation = (cost - salvage_value) / useful_life_months if useful_life_months > 0 else 0
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO assets (user_id, name, category, purchase_date, cost, useful_life_months,
                          salvage_value, monthly_depreciation, accumulated_depreciation, current_value)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s)
    """, (session['user_id'], name, category, purchase_date, cost, useful_life_months,
          salvage_value, monthly_depreciation, cost))
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Asset "{name}" added — ₱{cost:,.2f} | Monthly depreciation: ₱{monthly_depreciation:,.2f}', 'success')
    return redirect(url_for('assets.assets'))


@assets_bp.route('/dispose_asset/<int:asset_id>')
def dispose_asset(asset_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE assets SET status = 'disposed' WHERE id = %s AND user_id = %s",
                   (asset_id, session['user_id']))
    db.commit()
    cursor.close()
    db.close()
    
    flash('Asset marked as disposed.', 'success')
    return redirect(url_for('assets.assets'))


@assets_bp.route('/delete_asset/<int:asset_id>')
def delete_asset(asset_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE assets SET deleted_at = NOW() WHERE id = %s AND user_id = %s AND deleted_at IS NULL",
                   (asset_id, session['user_id']))
    db.commit()
    cursor.close()
    db.close()
    
    flash('Asset deleted.', 'success')
    return redirect(url_for('assets.assets'))