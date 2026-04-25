from flask import Flask, session, redirect, url_for
from models.helpers import user_has_feature
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

@app.context_processor
def inject_plan():
    if 'user_id' in session:
        return {
            'user_plan': session.get('plan', 'basic'),
            'user_plan_name': session.get('plan_name', 'Basic'),
            'has_feature': lambda feature: user_has_feature(session['user_id'], feature)
        }
    return {
        'user_plan': 'basic',
        'user_plan_name': 'Basic',
        'has_feature': lambda feature: False
    }

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard.dashboard'))
    return redirect(url_for('auth.login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')