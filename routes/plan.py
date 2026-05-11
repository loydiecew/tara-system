from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from models.database import get_db

plan_bp = Blueprint('plan', __name__)

@plan_bp.route('/plan')
def plan():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    current_plan_slug = session.get('plan', 'starter')
    
    return render_template('plan.html', 
                         current_plan_slug=current_plan_slug)

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

@plan_bp.route('/plan/start_trial/<module_code>', methods=['POST'])
def start_trial(module_code):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    if session.get('plan') not in ['essentials', 'professional']:
        return jsonify({'success': False, 'error': 'Trials available on Essentials and Professional plans'}), 403
    
    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor()
    
    # Check if already trialed
    cursor.execute("SELECT id FROM user_addons WHERE user_id = %s AND module_code = %s", (user_id, module_code))
    existing = cursor.fetchone()
    if existing:
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': 'You have already used the trial for this module'}), 400
    
    # Start trial
    trial_end = datetime.now() + timedelta(days=14)
    cursor.execute("""
        INSERT INTO user_addons (user_id, module_code, status, trial_ends_at, created_at)
        VALUES (%s, %s, 'trial', %s, NOW())
    """, (user_id, module_code, trial_end))
    db.commit()
    cursor.close()
    db.close()
    
    return jsonify({'success': True, 'message': 'Trial started! 14 days free.'})