from flask import Blueprint, render_template, session, redirect, url_for, request, flash
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
    
    # Get ALL add-on modules
    cursor.execute("SELECT * FROM modules ORDER BY price ASC")
    all_modules = cursor.fetchall()
    
    # Get purchased module IDs for this user
    cursor.execute("""
        SELECT module_id FROM user_modules 
        WHERE user_id = %s AND is_active = 1
    """, (session['user_id'],))
    purchased = cursor.fetchall()
    purchased_ids = [p['module_id'] for p in purchased]
    
    # Separate available vs purchased
    available_modules = [m for m in all_modules if m['id'] not in purchased_ids]
    purchased_modules = [m for m in all_modules if m['id'] in purchased_ids]
    
    cursor.close()
    db.close()
    
    return render_template('plan.html', 
                         username=session['username'],
                         plans=all_plans,
                         current_plan=current_plan,
                         available_modules=available_modules,
                         purchased_modules=purchased_modules)

@plan_bp.route('/purchase_module/<int:module_id>')
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
        cursor.execute("""
            INSERT INTO user_modules (user_id, module_id, is_active)
            VALUES (%s, %s, 1)
        """, (session['user_id'], module_id))
        db.commit()
        flash('Module added to your plan!', 'success')
    else:
        flash('Module already purchased.', 'info')
    
    cursor.close()
    db.close()
    
    return redirect(url_for('plan.plan'))

@plan_bp.route('/upgrade_plan/<int:plan_id>')
def upgrade_plan(plan_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Update user's plan
    cursor.execute("UPDATE users SET plan_id = %s WHERE id = %s", (plan_id, session['user_id']))
    db.commit()
    
    # Update session
    cursor.execute("SELECT slug, name FROM plans WHERE id = %s", (plan_id,))
    plan = cursor.fetchone()
    session['plan'] = plan['slug']
    session['plan_name'] = plan['name']
    
    cursor.close()
    db.close()
    
    flash(f'Plan upgraded to {plan["name"]}!', 'success')
    return redirect(url_for('plan.plan'))

@plan_bp.route('/switch_plan/<plan_slug>', methods=['POST'])
def switch_plan(plan_slug):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    plan_map = {
        'starter': 1,
        'essentials': 2,
        'professional': 3
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