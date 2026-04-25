from flask import Blueprint, render_template, session, redirect, url_for
from models.database import get_db
from models.helpers import get_user_plan

plan_bp = Blueprint('plan', __name__)

@plan_bp.route('/plan')
def plan():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM plans ORDER BY price_monthly ASC")
    all_plans = cursor.fetchall()
    
    current_plan = get_user_plan(session['user_id'])
    
    cursor.close()
    db.close()
    
    return render_template('plan.html',
                         username=session['username'],
                         plans=all_plans,
                         current_plan=current_plan)