from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from models.database import get_db

branches_bp = Blueprint('branches', __name__)

@branches_bp.route('/branches')
def branches():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('plan') not in ['enterprise']:
        flash('Multi-branch is available on Enterprise plan only.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT * FROM branches WHERE business_id = %s ORDER BY name
    """, (business_id,))
    branches = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('branches.html',
                         username=session['username'],
                         branches=branches)


@branches_bp.route('/add_branch', methods=['POST'])
def add_branch():
    if 'user_id' not in session or session.get('role') not in ['admin', 'owner']:
        return redirect(url_for('auth.login'))
    
    name = request.form['name']
    address = request.form.get('address', '')
    phone = request.form.get('phone', '')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO branches (business_id, name, address, phone)
        VALUES (%s, %s, %s, %s)
    """, (session.get('business_id'), name, address, phone))
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Branch "{name}" created!', 'success')
    return redirect(url_for('branches.branches'))


@branches_bp.route('/delete_branch/<int:branch_id>')
def delete_branch(branch_id):
    if 'user_id' not in session or session.get('role') not in ['admin', 'owner']:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE branches SET is_active = 0 WHERE id = %s AND business_id = %s",
                   (branch_id, session.get('business_id')))
    db.commit()
    cursor.close()
    db.close()
    
    flash('Branch deactivated.', 'success')
    return redirect(url_for('branches.branches'))


@branches_bp.route('/set_branch', methods=['POST'])
def set_branch():
    """Set active branch filter for session"""
    branch_id = request.form.get('branch_id', 'all')
    session['active_branch'] = branch_id if branch_id != 'all' else None
    return redirect(request.referrer or url_for('dashboard.dashboard'))