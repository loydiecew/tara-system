from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from models.database import get_db

permissions_bp = Blueprint('permissions', __name__)

ALL_MODULES = [
    ('dashboard', 'Dashboard'),
    ('insights', 'Business Insights'),
    ('cash', 'Cash Management'),
    ('sales', 'Sales Management'),
    ('ar', 'Accounts Receivable'),
    ('ap', 'Accounts Payable'),
    ('inventory', 'Inventory'),
    ('purchase_orders', 'Purchase Orders'),
    ('sales_orders', 'Sales Orders'),
    ('quotations', 'Quotations'),
    ('budgets', 'Budgeting'),
    ('projects', 'Projects'),
    ('timecards', 'Timecards'),
    ('assets', 'Fixed Assets'),
    ('journal', 'General Journal'),
    ('ledger', 'General Ledger'),
    ('all_transactions', 'All Transactions'),
    ('trial_balance', 'Trial Balance'),
    ('income_statement', 'Income Statement'),
    ('balance_sheet', 'Balance Sheet'),
    ('recurring', 'Recurring'),
    ('bank_reconciliation', 'Bank Reconciliation'),
    ('tax', 'Tax Reports'),
    ('currencies', 'Currencies'),
    ('reports', 'Reports'),
    ('import_data', 'Import Data'),
    ('branches', 'Branches'),
    ('fiscal_year', 'Fiscal Year'),
]

@permissions_bp.route('/permissions')
def permissions():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('plan') not in ['enterprise'] or session.get('role') not in ['admin', 'owner']:
        flash('Advanced permissions available on Enterprise plan only.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id')
    
    cursor.execute("SELECT * FROM custom_roles WHERE business_id = %s", (business_id,))
    roles = cursor.fetchall()
    
    for role in roles:
        cursor.execute("SELECT * FROM role_permissions WHERE role_id = %s", (role['id'],))
        role['permissions'] = cursor.fetchall()
    
    # Get users with custom roles
    cursor.execute("""
        SELECT u.id, u.username, u.custom_role_id, cr.name as role_name
        FROM users u
        LEFT JOIN custom_roles cr ON u.custom_role_id = cr.id
        WHERE u.business_id = %s
    """, (business_id,))
    users = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('permissions.html',
                         username=session['username'],
                         roles=roles,
                         users=users,
                         modules=ALL_MODULES)


@permissions_bp.route('/add_role', methods=['POST'])
def add_role():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    name = request.form['name']
    business_id = session.get('business_id')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO custom_roles (business_id, name) VALUES (%s, %s)", (business_id, name))
    role_id = cursor.lastrowid
    
    # Set permissions from form
    for module_code, module_name in ALL_MODULES:
        can_view = 1 if request.form.get(f'{module_code}_view') else 0
        can_create = 1 if request.form.get(f'{module_code}_create') else 0
        can_edit = 1 if request.form.get(f'{module_code}_edit') else 0
        can_delete = 1 if request.form.get(f'{module_code}_delete') else 0
        
        cursor.execute("""
            INSERT INTO role_permissions (role_id, module, can_view, can_create, can_edit, can_delete)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (role_id, module_code, can_view, can_create, can_edit, can_delete))
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Role "{name}" created!', 'success')
    return redirect(url_for('permissions.permissions'))


@permissions_bp.route('/delete_role/<int:role_id>')
def delete_role(role_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM custom_roles WHERE id = %s", (role_id,))
    db.commit()
    cursor.close()
    db.close()
    
    flash('Role deleted.', 'success')
    return redirect(url_for('permissions.permissions'))


@permissions_bp.route('/assign_role', methods=['POST'])
def assign_role():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    user_id = request.form['user_id']
    role_id = request.form.get('role_id') or None
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE users SET custom_role_id = %s WHERE id = %s", (role_id if role_id else None, user_id))
    db.commit()
    cursor.close()
    db.close()
    
    flash('User role updated.', 'success')
    return redirect(url_for('permissions.permissions'))