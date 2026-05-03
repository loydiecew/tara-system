from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from models.database import get_db
from models.access_control import check_module_access

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
    return redirect(url_for('admin.users_roles'))

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
    cursor = db.cursor(dictionary=True)
    
    if role_id:
        cursor.execute("SELECT name FROM custom_roles WHERE id = %s", (role_id,))
        role_data = cursor.fetchone()
        role_name = role_data['name'] if role_data else ''
        
        # Use the actual role name as the base role
        base_role = role_name.lower().replace(' ', '_')
        
        cursor.execute("UPDATE users SET custom_role_id = %s, role = %s WHERE id = %s", 
                      (role_id, base_role, user_id))
    else:
        cursor.execute("UPDATE users SET custom_role_id = NULL, role = 'cashier' WHERE id = %s", (user_id,))
    
    db.commit()
    cursor.close()
    db.close()
    
    flash('User role updated!', 'success')
    return redirect(url_for('admin.users_roles'))
    
def create_enterprise_role_templates(business_id, user_id):
    """Create pre-built role templates when upgrading to Enterprise"""
    db = get_db()
    cursor = db.cursor(dictionary=True) 
    
    # Check if roles already exist for this business
    cursor.execute("SELECT COUNT(*) as count FROM custom_roles WHERE business_id = %s", (business_id,))
    if cursor.fetchone()['count'] > 0:
            cursor.close()
            db.close()
            return  # Already has roles, skip
    
    templates = {
        'Owner': {
            'all_modules': True
        },
        'Admin': {
            'all_modules': True
        },
        'Branch Manager': {
            'modules': ['dashboard','insights','reports','cash','sales','recurring',
                       'bank_reconciliation','tax','currencies','inventory',
                       'purchase_orders','sales_orders','ar','ap',
                       'journal','all_transactions','income_statement','balance_sheet',
                       'trial_balance','ledger','branches']
        },
        'Manager': {
            'modules': ['dashboard','insights','reports','cash','sales','recurring',
                       'bank_reconciliation','tax','currencies','inventory',
                       'purchase_orders','sales_orders','journal',
                       'income_statement','balance_sheet']
        },
        'Cashier': {
            'modules': ['dashboard','insights','reports','cash','sales',
                       'journal','income_statement','balance_sheet'],
            'restrictions': {'cash': {'create_only': True, 'income_only': True}}
        },
        'Accountant': {
            'modules': ['dashboard','insights','reports','cash','sales','ar','ap',
                       'journal','ledger','trial_balance','all_transactions',
                       'income_statement','balance_sheet','tax','bank_reconciliation',
                       'recurring','currencies','fiscal_year','budgets'],
            'read_only': True
        },
        'Auditor': {
            'modules': ['dashboard','insights','reports','cash','sales','ar','ap',
                       'inventory','journal','ledger','trial_balance','all_transactions',
                       'income_statement','balance_sheet','tax','bank_reconciliation',
                       'audit_log'],
            'read_only': True
        }
    }
    
    for role_name, config in templates.items():
        # Create role
        cursor.execute("""
            INSERT INTO custom_roles (business_id, name) VALUES (%s, %s)
        """, (business_id, role_name))
        role_id = cursor.lastrowid
        
        if config.get('all_modules'):
            # Grant all permissions
            from routes.permissions import ALL_MODULES
            for module_code, _ in ALL_MODULES:
                cursor.execute("""
                    INSERT INTO role_permissions (role_id, module, can_view, can_create, can_edit, can_delete)
                    VALUES (%s, %s, 1, 1, 1, 1)
                """, (role_id, module_code))
        else:
            # Grant specific modules
            is_readonly = config.get('read_only', False)
            for module_code in config.get('modules', []):
                cursor.execute("""
                    INSERT INTO role_permissions (role_id, module, can_view, can_create, can_edit, can_delete)
                    VALUES (%s, %s, 1, %s, %s, %s)
                """, (role_id, module_code, 
                      0 if is_readonly else 1,
                      0 if is_readonly else 1,
                      0 if is_readonly else 1))
    
    db.commit()
    cursor.close()
    db.close()

@permissions_bp.route('/update_role_permissions', methods=['POST'])
def update_role_permissions():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    role_id = request.form['role_id']
    
    db = get_db()
    cursor = db.cursor()
    
    # Get all submitted module permissions
    submitted_modules = set()
    
    for module_code, _ in ALL_MODULES:
        can_view = 1 if request.form.get(f'{module_code}_view') else 0
        can_create = 1 if request.form.get(f'{module_code}_create') else 0
        can_edit = 1 if request.form.get(f'{module_code}_edit') else 0
        can_delete = 1 if request.form.get(f'{module_code}_delete') else 0
        
        # Check if this module has any permissions set
        if can_view or can_create or can_edit or can_delete:
            submitted_modules.add(module_code)
            
            # Check if permission row exists
            cursor.execute("SELECT id FROM role_permissions WHERE role_id = %s AND module = %s", (role_id, module_code))
            existing = cursor.fetchone()
            
            if existing:
                # Update existing
                cursor.execute("""
                    UPDATE role_permissions 
                    SET can_view = %s, can_create = %s, can_edit = %s, can_delete = %s
                    WHERE role_id = %s AND module = %s
                """, (can_view, can_create, can_edit, can_delete, role_id, module_code))
            else:
                # Insert new
                cursor.execute("""
                    INSERT INTO role_permissions (role_id, module, can_view, can_create, can_edit, can_delete)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (role_id, module_code, can_view, can_create, can_edit, can_delete))
        else:
            # No permissions set — delete the row if it exists
            cursor.execute("DELETE FROM role_permissions WHERE role_id = %s AND module = %s", (role_id, module_code))
    
    db.commit()
    cursor.close()
    db.close()
    
    flash('Role permissions updated!', 'success')
    return redirect(url_for('permissions.permissions'))