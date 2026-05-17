import os
from flask import Flask, session, redirect, url_for, request, render_template
from flask_mail import Mail
from models.database import get_db
from routes.permissions import create_enterprise_role_templates
from models.helpers import user_has_feature, user_has_addon

# ---------- Import all blueprints ----------
from routes import (
    records_bp,
    scratchpad_bp,
    auth_bp, dashboard_bp, quick_tap_bp, cash_bp, sales_bp, journal_bp,
    ar_bp, ap_bp, inventory_bp, insights_bp, admin_bp, plan_bp, api_bp,
    all_transactions_bp, import_bp, orders_bp, quotations_bp,
    budgets_bp, projects_bp, timecards_bp, assets_bp, reports_bp, planner_bp,
    branches_bp, payments_bp, recurring_bp, bank_rec_bp,
    fiscal_bp, tax_bp, currencies_bp, permissions_bp, tasks_bp, approvals_bp 
)
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
    records_bp,
    scratchpad_bp,
    approvals_bp,
    tasks_bp,
    auth_bp, dashboard_bp, quick_tap_bp, cash_bp, sales_bp, journal_bp,
    ar_bp, ap_bp, inventory_bp, insights_bp, admin_bp, plan_bp, api_bp,
    all_transactions_bp, import_bp, orders_bp, quotations_bp,
    budgets_bp, projects_bp, timecards_bp, assets_bp, reports_bp,
    branches_bp, payments_bp, recurring_bp, bank_rec_bp,
    fiscal_bp, tax_bp, currencies_bp, permissions_bp, planner_bp
]
for bp in BLUEPRINTS:
    app.register_blueprint(bp)

# ---------- Context processors ----------
@app.context_processor
def inject_user_context():
    """Inject user, plan, and permission helpers into all templates."""
    def is_active(endpoint_name):
        if not request.endpoint:
            return ''
        return 'active' if request.endpoint.endswith(endpoint_name) else ''

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

    # Get user count for the business (for TEAM section gating)
    user_count = 0
    if 'user_id' in session:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE business_id = %s", (session.get('business_id', session.get('user_id')),))
        user_count = cursor.fetchone()[0]
        cursor.close()
        db.close()

    ctx = {
        'is_active': is_active,
        'get_branches': get_branches,
        'user_can_view': user_can_view,
        'user_count': user_count,
    }

    if 'user_id' in session:
        ctx.update({
            'user_plan': session.get('plan', 'starter'),
            'user_plan_name': session.get('plan_name', 'Starter'),
            'has_feature': lambda feature: user_has_feature(session['user_id'], feature),
            'user_has_addon': lambda module: user_has_addon(module),
        })
    else:
        ctx.update({
            'user_plan': 'starter',
            'user_plan_name': 'Starter',
            'has_feature': lambda feature: False,
            'user_has_addon': lambda module: False,
            'get_branches': lambda: [],
            'user_can_view': lambda m: True,
        })

    return ctx

# ---------- Public routes ----------
@app.route('/')
def home():
    if 'user_id' in session:
        if session.get('plan') == 'starter':
            return redirect(url_for('quick_tap.index'))
        return redirect(url_for('dashboard.dashboard'))
    return render_template('landing.html')


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/terms')
def terms():
    return render_template('terms.html')


# ---------- Plan upgrade shortcuts (kept for compatibility) ----------
@app.route('/upgrade_to_pro')
def upgrade_to_pro():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    _update_plan(3, 'professional', 'Professional')
    return redirect(url_for('plan.plan'))


@app.route('/upgrade_to_enterprise')
def upgrade_to_enterprise():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    _update_plan(4, 'suite', 'Suite')
    create_enterprise_role_templates(session.get('business_id'), session['user_id'])
    return redirect(url_for('plan.plan'))


@app.route('/switch_to_basic')
def switch_to_basic():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    _update_plan(1, 'starter', 'Starter')
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


@app.route('/favicon.ico')
def favicon():
    return '', 204

# ---------- Error handlers ----------
@app.errorhandler(404)
def not_found(e):
    return '<!DOCTYPE html><html><head><title>404 - TARA</title><style>body{font-family:Inter,sans-serif;background:#060608;color:#f1f1f3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center} h1{font-size:48px;color:#10b981} p{color:#a1a1aa} a{color:#10b981}</style></head><body><div><h1>404</h1><p>Page not found</p><a href="/">Go Home</a></div></body></html>', 404


@app.errorhandler(500)
def server_error(e):
    return '<!DOCTYPE html><html><head><title>500 - TARA</title><style>body{font-family:Inter,sans-serif;background:#060608;color:#f1f1f3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center} h1{font-size:48px;color:#f59e0b} p{color:#a1a1aa} a{color:#10b981}</style></head><body><div><h1>500</h1><p>Something went wrong</p><a href="/">Go Home</a></div></body></html>', 500


# ---------- Run ----------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')