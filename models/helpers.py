from flask import session
from models.database import get_db
from datetime import timedelta

def can_user_access(session, module_name, action='view'):
    """Centralized role-based access control.
    
    Args:
        session: Flask session object
        module_name: e.g., 'reports', 'ar', 'settings', 'billing'
        action: 'view', 'create', 'edit', 'delete', 'approve'
    
    Returns:
        bool: Whether the user can perform the action
    """
    role = session.get('role', 'viewer')
    plan = session.get('plan', 'starter')
    
    # Owner can do everything
    if role == 'owner':
        return True
    
    # Viewer is read-only on view action, nothing else
    if role in ['viewer', 'auditor']:
        return action == 'view'
    
    # Cashier restrictions
    if role == 'cashier':
        cashier_allowed = {
            'dashboard': ['view'],
            'quick_tap': ['view', 'create'],
            'cash': ['view', 'create'],
            'sales': ['view', 'create'],
            'ar': ['view', 'create'],
            'journal': ['view'],
            'tasks': ['view'],
            'all_transactions': ['view'],
            'income_statement': ['view'],
            'balance_sheet': ['view'],
        }
        allowed = cashier_allowed.get(module_name, [])
        return action in allowed
    
    # Manager restrictions
    if role == 'manager':
        manager_restricted = {
            'billing': [],
            'users_roles': ['view'],
            'settings': ['view'],
            'permissions': ['view'],
            'audit_log': ['view'],
            'fiscal_year': [],
            'branches': [],
            'currencies': ['view'],
            'tax': ['view'],
            'import_data': ['view', 'create'],
        }
        restricted = manager_restricted.get(module_name, None)
        if restricted is not None:
            return action in restricted
        return True
    
    # Admin — full access except billing
    if role == 'admin':
        if module_name == 'billing':
            return False
        return True
    
    return False


def can_user_edit(session, module_name):
    """Shorthand for edit permission check."""
    return can_user_access(session, module_name, 'edit')


def can_user_create(session, module_name):
    """Shorthand for create permission check."""
    return can_user_access(session, module_name, 'create')


def can_user_delete(session, module_name):
    """Shorthand for delete permission check."""
    return can_user_access(session, module_name, 'delete')


def get_role_label(role):
    """Return display label for role."""
    labels = {
        'owner': 'Owner',
        'admin': 'Admin', 
        'manager': 'Manager',
        'cashier': 'Cashier',
        'viewer': 'Viewer',
    }
    return labels.get(role, role.title())


def get_user_plan(user_id):
    """Get user's current plan"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.id, p.name, p.slug, p.price_monthly, p.max_users 
        FROM users u
        JOIN plans p ON u.plan_id = p.id
        WHERE u.id = %s
    """, (user_id,))
    plan = cursor.fetchone()
    cursor.close()
    db.close()
    return plan

def user_has_feature(user_id, feature_name):
    """Check if user's plan includes a specific feature"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT COUNT(*) as has_feature
        FROM users u
        JOIN plans p ON u.plan_id = p.id
        JOIN plan_features pf ON p.id = pf.plan_id
        JOIN features f ON pf.feature_id = f.id
        WHERE u.id = %s AND f.name = %s
    """, (user_id, feature_name))
    result = cursor.fetchone()
    cursor.close()
    db.close()
    return result['has_feature'] > 0

def get_user_features(user_id):
    """Get list of features available to user"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT f.name
        FROM users u
        JOIN plans p ON u.plan_id = p.id
        JOIN plan_features pf ON p.id = pf.plan_id
        JOIN features f ON pf.feature_id = f.id
        WHERE u.id = %s
    """, (user_id,))
    features = [row['name'] for row in cursor.fetchall()]
    cursor.close()
    db.close()
    return features

def user_has_module(user_id, module_name):
    """Check if user has purchased a specific module or it's included in their plan"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # First check if module is included in plan
    cursor.execute("""
        SELECT COUNT(*) as has_feature
        FROM users u
        JOIN plans p ON u.plan_id = p.id
        JOIN plan_features pf ON p.id = pf.plan_id
        JOIN features f ON pf.feature_id = f.id
        WHERE u.id = %s AND f.name = %s
    """, (user_id, module_name))
    result = cursor.fetchone()
    
    if result['has_feature'] > 0:
        cursor.close()
        db.close()
        return True
    
    # Then check if purchased as add-on
    cursor.execute("""
        SELECT COUNT(*) as has_module
        FROM user_modules um
        JOIN modules m ON um.module_id = m.id
        WHERE um.user_id = %s AND m.name = %s AND um.is_active = 1
    """, (user_id, module_name))
    result = cursor.fetchone()
    
    cursor.close()
    db.close()
    return result['has_module'] > 0

def get_week_range(date_obj):
    """Returns Monday and Sunday of the week containing date_obj"""
    start_of_week = date_obj - timedelta(days=date_obj.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week

def user_has_addon(module_code):
    """Check if user has active add-on or trial."""
    if 'user_id' not in session:
        return False
    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT id FROM user_addons 
        WHERE user_id = %s AND module_code = %s 
        AND (status = 'active' OR (status = 'trial' AND trial_ends_at > NOW()))
    """, (user_id, module_code))
    result = cursor.fetchone()
    cursor.close()
    db.close()
    return bool(result)