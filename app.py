from flask import Flask, session, redirect, url_for, request
from models.helpers import user_has_feature
from routes.all_transactions import all_transactions_bp
from routes.import_data import import_bp
from routes.orders import orders_bp
from routes.quotations import quotations_bp
from flask_mail import Mail, Message
from models.database import get_db 
from routes.budgets import budgets_bp
from routes.projects import projects_bp
from routes.timecards import timecards_bp
from routes.assets import assets_bp
from routes.reports import reports_bp
from routes.branches import branches_bp
from routes.payments import payments_bp
from routes.recurring import recurring_bp
from routes.bank_reconciliation import bank_rec_bp
from routes.fiscal_year import fiscal_bp
from routes.tax import tax_bp
from routes.currencies import currencies_bp
from routes.permissions import permissions_bp
from routes import (
    auth_bp, dashboard_bp, cash_bp, sales_bp, journal_bp,
    ar_bp, ap_bp, inventory_bp, insights_bp, admin_bp, plan_bp, api_bp
)

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = 'tara-secret-key'
# Email Configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = 'casupangloydmatthew1234@gmail.com'    
app.config['MAIL_PASSWORD'] = 'eosphyqdtfslqzdj'             
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
mail = Mail(app)

# Register all blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(cash_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(journal_bp)
app.register_blueprint(ar_bp)
app.register_blueprint(ap_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(insights_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(plan_bp)
app.register_blueprint(api_bp)
app.register_blueprint(all_transactions_bp)
app.register_blueprint(import_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(quotations_bp)
app.register_blueprint(budgets_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(timecards_bp)
app.register_blueprint(assets_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(branches_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(recurring_bp)
app.register_blueprint(bank_rec_bp)
app.register_blueprint(fiscal_bp)
app.register_blueprint(tax_bp)
app.register_blueprint(currencies_bp)
app.register_blueprint(permissions_bp)


@app.context_processor
def inject_plan():
    def is_active(endpoint_name):
        return 'active' if request.endpoint and request.endpoint.endswith(endpoint_name) else ''
    
    def get_branches():
        if 'user_id' not in session:
            return []
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id, name FROM branches WHERE business_id = %s AND is_active = 1", 
                      (session.get('business_id', session.get('user_id')),))
        branches = cursor.fetchall()
        cursor.close()
        db.close()
        return branches
    
    if 'user_id' in session:
        return {
            'user_plan': session.get('plan', 'basic'),
            'user_plan_name': session.get('plan_name', 'Basic'),
            'has_feature': lambda feature: user_has_feature(session['user_id'], feature),
            'is_active': is_active,
            'get_branches': get_branches
        }
    return {
        'user_plan': 'basic',
        'user_plan_name': 'Basic',
        'has_feature': lambda feature: False,
        'is_active': is_active,
        'get_branches': lambda: []
    }

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard.dashboard'))
    return redirect(url_for('auth.login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')

@app.route('/upgrade_to_pro')
def upgrade_to_pro():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    # Update database
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE users SET plan_id = 2 WHERE id = %s", (session['user_id'],))
    db.commit()
    cursor.close()
    db.close()
    
    # Update session
    session['plan'] = 'pro'
    session['plan_name'] = 'Pro'
    
    return redirect(url_for('plan.plan'))

@app.route('/switch_to_basic')
def switch_to_basic():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE users SET plan_id = 1 WHERE id = %s", (session['user_id'],))
    db.commit()
    cursor.close()
    db.close()
    
    session['plan'] = 'basic'
    session['plan_name'] = 'Basic'
    
    return redirect(url_for('plan.plan'))

