import os
from flask import Flask, session, redirect, url_for, request
from flask_mail import Mail
from models.database import get_db
from models.helpers import user_has_feature
from routes.permissions import create_enterprise_role_templates

# ---------- Import all blueprints ----------
from routes import (
    auth_bp, dashboard_bp, cash_bp, sales_bp, journal_bp,
    ar_bp, ap_bp, inventory_bp, insights_bp, admin_bp, plan_bp, api_bp,
    all_transactions_bp, import_bp, orders_bp, quotations_bp,
    budgets_bp, projects_bp, timecards_bp, assets_bp, reports_bp,
    branches_bp, payments_bp, recurring_bp, bank_rec_bp,
    fiscal_bp, tax_bp, currencies_bp, permissions_bp
)

# ---------- App setup ----------
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'tara-dev-key')
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Email
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
mail = Mail(app)

# ---------- Register blueprints ----------
BLUEPRINTS = [
    auth_bp, dashboard_bp, cash_bp, sales_bp, journal_bp,
    ar_bp, ap_bp, inventory_bp, insights_bp, admin_bp, plan_bp, api_bp,
    all_transactions_bp, import_bp, orders_bp, quotations_bp,
    budgets_bp, projects_bp, timecards_bp, assets_bp, reports_bp,
    branches_bp, payments_bp, recurring_bp, bank_rec_bp,
    fiscal_bp, tax_bp, currencies_bp, permissions_bp
]
for bp in BLUEPRINTS:
    app.register_blueprint(bp)

# ---------- Context processors ----------
@app.context_processor
def inject_plan():
    def is_active(endpoint_name):
        return 'active' if request.endpoint and request.endpoint.endswith(endpoint_name) else ''

    def get_branches():
        if 'user_id' not in session:
            return []
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, name FROM branches WHERE business_id = %s AND is_active = 1",
            (session.get('business_id', session.get('user_id')),)
        )
        branches = cursor.fetchall()
        cursor.close()
        db.close()
        return branches

    def user_can_view(module_name):
        if 'user_id' not in session:
            return False
        if session.get('plan') != 'enterprise':
            return True
        custom_role_id = session.get('custom_role_id')
        if not custom_role_id:
            return True
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("""
            SELECT can_view FROM role_permissions 
            WHERE role_id = %s AND module = %s
        """, (custom_role_id, module_name))
        result = cursor.fetchone()
        cursor.close()
        db.close()
        return bool(result and result['can_view'])

    if 'user_id' in session:
        return {
            'user_plan': session.get('plan', 'basic'),
            'user_plan_name': session.get('plan_name', 'Basic'),
            'has_feature': lambda feature: user_has_feature(session['user_id'], feature),
            'is_active': is_active,
            'get_branches': get_branches,
            'user_can_view': user_can_view
        }
    return {
        'user_plan': 'basic',
        'user_plan_name': 'Basic',
        'has_feature': lambda feature: False,
        'is_active': is_active,
        'get_branches': lambda: [],
        'user_can_view': lambda m: True
    }

# ---------- Routes ----------
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard.dashboard'))
    return redirect(url_for('auth.login'))

@app.route('/upgrade_to_pro')
def upgrade_to_pro():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    _update_plan(2, 'pro', 'Pro')
    return redirect(url_for('plan.plan'))

@app.route('/upgrade_to_enterprise')
def upgrade_to_enterprise():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    _update_plan(3, 'enterprise', 'Enterprise')
    create_enterprise_role_templates(session.get('business_id'), session['user_id'])
    return redirect(url_for('plan.plan'))

@app.route('/switch_to_basic')
def switch_to_basic():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    _update_plan(1, 'basic', 'Basic')
    return redirect(url_for('plan.plan'))

# ---------- Helpers ----------
def _update_plan(plan_id, plan_key, plan_name):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE users SET plan_id = %s WHERE id = %s", (plan_id, session['user_id']))
    db.commit()
    cursor.close()
    db.close()
    session['plan'] = plan_key
    session['plan_name'] = plan_name

# ---------- Run ----------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')