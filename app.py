from flask import Flask, session, redirect, url_for, request
from models.helpers import user_has_feature
from routes.all_transactions import all_transactions_bp
from routes import (
    auth_bp, dashboard_bp, cash_bp, sales_bp, journal_bp,
    ar_bp, ap_bp, inventory_bp, insights_bp, admin_bp, plan_bp, api_bp
)

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = 'tara-secret-key'

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
from routes.import_data import import_bp
app.register_blueprint(import_bp)
from routes.orders import orders_bp
app.register_blueprint(orders_bp)


@app.context_processor
def inject_plan():
    def is_active(endpoint_name):
        """Returns 'active' if current endpoint ends with the given name"""
        return 'active' if request.endpoint and request.endpoint.endswith(endpoint_name) else ''
    
    if 'user_id' in session:
        return {
            'user_plan': session.get('plan', 'basic'),
            'user_plan_name': session.get('plan_name', 'Basic'),
            'has_feature': lambda feature: user_has_feature(session['user_id'], feature),
            'is_active': is_active
        }
    return {
        'user_plan': 'basic',
        'user_plan_name': 'Basic',
        'has_feature': lambda feature: False,
        'is_active': is_active
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