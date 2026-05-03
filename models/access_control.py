from flask import session, flash, redirect, url_for
from models.database import get_db

def check_module_access(module_name, action='view'):
    """Check if user can access a module. Redirects if not."""
    if 'user_id' not in session:
        return False  # Let the route's login check handle this
    
    # Non-enterprise or no custom role = use default role checks
    if session.get('plan') != 'enterprise' or not session.get('custom_role_id'):
        return True
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(f"SELECT can_{action} FROM role_permissions WHERE role_id = %s AND module = %s",
                   (session['custom_role_id'], module_name))
    result = cursor.fetchone()
    cursor.close()
    db.close()
    
    if not result or not result[f'can_{action}']:
        flash('Access restricted by your role permissions.', 'error')
        return False
    
    return True