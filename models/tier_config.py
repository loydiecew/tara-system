# Tier Access Configuration

TIER_MODULES = {
    'basic': {
        'included': [
            'dashboard', 'insights', 'cash', 'sales', 'journal',
            'all_transactions', 'income_statement', 'balance_sheet',
            'reports', 'help', 'profile'
        ],
        'addons': {
            'import_data': 200,
            'export_csv': 100,
            'email_receipts': 150
        }
    },
    'pro': {
        'included': [
            'dashboard', 'insights', 'cash', 'sales', 'journal',
            'all_transactions', 'income_statement', 'balance_sheet',
            'reports', 'help', 'profile',
            'ar', 'ap', 'inventory', 'purchase_orders', 'sales_orders',
            'ledger', 'trial_balance', 'bank_reconciliation', 'tax',
            'import_data', 'export_csv', 'email_receipts'
        ],
        'addons': {
            'quotations': 500,
            'budgeting': 400,
            'projects': 400,
            'timecards': 300,
            'fixed_assets': 400,
            'recurring': 200,
            'currencies': 200,
            'payment_links': 400,
            'email_blast': 300
        }
    },
    'enterprise': {
        'included': [
            'dashboard', 'insights', 'cash', 'sales', 'journal',
            'all_transactions', 'income_statement', 'balance_sheet',
            'reports', 'help', 'profile',
            'ar', 'ap', 'inventory', 'purchase_orders', 'sales_orders',
            'ledger', 'trial_balance', 'bank_reconciliation', 'tax',
            'import_data', 'export_csv', 'email_receipts',
            'quotations', 'budgeting', 'projects', 'timecards',
            'fixed_assets', 'recurring', 'currencies', 'payment_links',
            'email_blast', 'branches', 'permissions', 'fiscal_year'
        ],
        'addons': {}  # Everything included
    }
}

def module_allowed(plan, module_name):
    """Check if a module is allowed for a given plan (included or addon)"""
    plan_config = TIER_MODULES.get(plan, TIER_MODULES['basic'])
    return module_name in plan_config['included'] or module_name in plan_config['addons']

def module_is_addon(plan, module_name):
    """Check if a module is an addon for a given plan"""
    plan_config = TIER_MODULES.get(plan, TIER_MODULES['basic'])
    return module_name in plan_config.get('addons', {})

def get_addon_price(plan, module_name):
    """Get addon price for a module"""
    plan_config = TIER_MODULES.get(plan, TIER_MODULES['basic'])
    return plan_config.get('addons', {}).get(module_name, 0)

def get_included_modules(plan):
    """Get list of included module names for a plan"""
    plan_config = TIER_MODULES.get(plan, TIER_MODULES['basic'])
    return plan_config['included']

def get_addon_modules(plan):
    """Get list of addon module names for a plan"""
    plan_config = TIER_MODULES.get(plan, TIER_MODULES['basic'])
    return list(plan_config.get('addons', {}).keys())

def user_has_module_access(user_id, module_name, action='view'):
    """Check if user has access to a module based on their custom role"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get user's custom role
    cursor.execute("SELECT custom_role_id, role FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    
    if not user or not user['custom_role_id']:
        # Fall back to default role-based access
        cursor.close()
        db.close()
        return True  # Default roles handled by existing checks
    
    # Check permission
    cursor.execute("""
        SELECT can_{action} FROM role_permissions 
        WHERE role_id = %s AND module = %s
    """.format(action=action), (user['custom_role_id'], module_name))
    
    result = cursor.fetchone()
    cursor.close()
    db.close()
    
    return result and result[f'can_{action}'] == 1