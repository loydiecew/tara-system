from flask import Blueprint, render_template, session, redirect, url_for, request
from models.database import get_db

plan_bp = Blueprint('plan', __name__)

@plan_bp.route('/plan')
def plan():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get all plans
    cursor.execute("SELECT * FROM plans ORDER BY price_monthly ASC")
    all_plans = cursor.fetchall()
    
    # Get current user's plan
    cursor.execute("SELECT p.* FROM users u JOIN plans p ON u.plan_id = p.id WHERE u.id = %s", (session['user_id'],))
    current_plan = cursor.fetchone()
    
    # Get ALL modules (for add-ons section)
    cursor.execute("SELECT * FROM modules ORDER BY price ASC")
    all_modules = cursor.fetchall()
    
    # Get purchased modules
    cursor.execute("""
        SELECT m.* FROM modules m
        JOIN user_modules um ON m.id = um.module_id
        WHERE um.user_id = %s AND um.is_active = 1
    """, (session['user_id'],))
    purchased_modules = cursor.fetchall()
    
    # Get purchased module IDs
    purchased_ids = [m['id'] for m in purchased_modules]
    
    # Available modules = all modules - purchased modules
    available_modules = [m for m in all_modules if m['id'] not in purchased_ids]
    
    cursor.close()
    db.close()
    
    return render_template('plan.html', 
                         username=session['username'],
                         plans=all_plans,
                         current_plan=current_plan,
                         available_modules=available_modules,
                         purchased_modules=purchased_modules)

@plan_bp.route('/purchase_module/<int:module_id>', methods=['POST'])
def purchase_module(module_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor()
    
    # Check if already purchased
    cursor.execute("SELECT * FROM user_modules WHERE user_id = %s AND module_id = %s", 
                   (session['user_id'], module_id))
    existing = cursor.fetchone()
    
    if not existing:
        # Add module to user's purchases
        cursor.execute("""
            INSERT INTO user_modules (user_id, module_id, is_active)
            VALUES (%s, %s, 1)
        """, (session['user_id'], module_id))
        db.commit()
    
    cursor.close()
    db.close()
    
    return redirect(url_for('plan.plan'))

@plan_bp.route('/switch_plan/<plan_slug>', methods=['POST'])
def switch_plan(plan_slug):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    plan_map = {
        'basic': 1,
        'pro': 2,
        'enterprise': 3
    }
    
    plan_id = plan_map.get(plan_slug, 1)
    
    db = get_db()
    cursor = db.cursor()
    
    # Update user's plan
    cursor.execute("UPDATE users SET plan_id = %s WHERE id = %s", (plan_id, session['user_id']))
    db.commit()
    
    # Update session
    session['plan'] = plan_slug
    session['plan_name'] = plan_slug.capitalize()
    
    cursor.close()
    db.close()
    
    return redirect(url_for('plan.plan'))