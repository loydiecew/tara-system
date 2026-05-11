from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date
from models.database import get_db
from models.access_control import check_module_access

timecards_bp = Blueprint('timecards', __name__)

@timecards_bp.route('/timecards')
def timecards():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if not check_module_access('timecards'): return redirect(url_for('dashboard.dashboard'))

    if session.get('plan') not in ['suite']:
        flash('Timecards are available on Enterprise plan only.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT t.*, p.name as project_name, p.client_name
        FROM timecards t
        LEFT JOIN projects p ON t.project_id = p.id
        JOIN users u ON t.user_id = u.id
        WHERE t.deleted_at IS NULL AND u.business_id = %s
        ORDER BY t.date_worked DESC
    """, (business_id,))
    timecards = cursor.fetchall()
    
    cursor.execute("""
        SELECT p.id, p.name FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE p.deleted_at IS NULL AND u.business_id = %s AND p.status = 'active'
    """, (business_id,))
    projects = cursor.fetchall()
    
    # Totals
    total_hours = sum(float(t['hours'] or 0) for t in timecards)
    total_amount = sum(float(t['amount'] or 0) for t in timecards)
    unbilled = sum(float(t['amount'] or 0) for t in timecards if t['status'] == 'unbilled')
    
    cursor.close()
    db.close()
    
    return render_template('timecards.html',
                         username=session['username'],
                         timecards=timecards,
                         projects=projects,
                         total_hours=total_hours,
                         total_amount=total_amount,
                         unbilled=unbilled,
                         today=date.today().isoformat())


@timecards_bp.route('/add_timecard', methods=['POST'])
def add_timecard():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    project_id = request.form.get('project_id') or None
    description = request.form.get('description', '')
    hours = float(request.form['hours'])
    rate = float(request.form['rate'])
    date_worked = request.form.get('date_worked', date.today())
    
    amount = hours * rate
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO timecards (user_id, project_id, description, hours, rate, amount, date_worked)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (session['user_id'], project_id, description, hours, rate, amount, date_worked))
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Timecard logged: {hours}h × ₱{rate:,.0f}/hr = ₱{amount:,.2f}', 'success')
    return redirect(url_for('timecards.timecards'))


@timecards_bp.route('/delete_timecard/<int:timecard_id>')
def delete_timecard(timecard_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE timecards SET deleted_at = NOW() WHERE id = %s AND user_id = %s AND status = 'unbilled' AND deleted_at IS NULL",
                   (timecard_id, session['user_id']))
    db.commit()
    cursor.close()
    db.close()
    
    flash('Timecard deleted.', 'success')
    return redirect(url_for('timecards.timecards'))


@timecards_bp.route('/bill_timecards', methods=['POST'])
def bill_timecards():
    """Generate an invoice from selected unbilled timecards"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    selected = request.form.getlist('timecard_ids')
    if not selected:
        flash('Select at least one timecard to bill.', 'error')
        return redirect(url_for('timecards.timecards'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get timecards
    placeholders = ','.join(['%s'] * len(selected))
    cursor.execute(f"""
        SELECT t.*, p.name as project_name, p.client_name
        FROM timecards t WHERE t.deleted_at IS NULL
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE t.id IN ({placeholders}) AND t.user_id = %s AND t.status = 'unbilled'
    """, (*selected, session['user_id']))
    timecards = cursor.fetchall()
    
    if not timecards:
        cursor.close()
        db.close()
        flash('No valid timecards selected.', 'error')
        return redirect(url_for('timecards.timecards'))
    
    total_amount = sum(float(t['amount']) for t in timecards)
    
    # Get or create customer from project
    project_name = timecards[0].get('project_name', '')
    client_name = timecards[0].get('client_name', 'Client')
    
    # Create invoice
    description = f"Professional services: {project_name or 'General'}"
    cursor.execute("""
        INSERT INTO invoices (user_id, invoice_number, amount, description, due_date, status)
        VALUES (%s, %s, %s, %s, %s, 'unpaid')
    """, (
        session['user_id'],
        f"INV-TC-{date.today().strftime('%Y%m%d')}",
        total_amount,
        description,
        date.today()
    ))
    invoice_id = cursor.lastrowid
    
    # Mark timecards as billed
    for tc in timecards:
        cursor.execute("UPDATE timecards SET status = 'billed', invoice_id = %s WHERE id = %s",
                      (invoice_id, tc['id']))
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Invoice created from {len(timecards)} timecards — ₱{total_amount:,.2f}', 'success')
    return redirect(url_for('ar.ar'))