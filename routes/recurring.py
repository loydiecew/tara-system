from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from models.database import get_db

recurring_bp = Blueprint('recurring', __name__)

def get_next_date(start_date, frequency):
    today = date.today()
    d = start_date
    while d <= today:
        if frequency == 'daily':
            d += timedelta(days=1)
        elif frequency == 'weekly':
            d += timedelta(weeks=1)
        elif frequency == 'monthly':
            d += relativedelta(months=1)
        elif frequency == 'quarterly':
            d += relativedelta(months=3)
        elif frequency == 'yearly':
            d += relativedelta(years=1)
    return d

@recurring_bp.route('/recurring')
def recurring():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT r.* FROM recurring_transactions r
        JOIN users u ON r.user_id = u.id
        WHERE u.business_id = %s
        ORDER BY r.next_date ASC
    """, (business_id,))
    transactions = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('recurring.html',
                         username=session['username'],
                         transactions=transactions,
                         today=date.today().isoformat())


@recurring_bp.route('/add_recurring', methods=['POST'])
def add_recurring():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    description = request.form['description']
    amount = float(request.form['amount'])
    trans_type = request.form['type']
    category = request.form.get('category', '')
    frequency = request.form['frequency']
    start_date = request.form.get('start_date', date.today())
    
    next_date = get_next_date(date.fromisoformat(start_date) if isinstance(start_date, str) else start_date, frequency)
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO recurring_transactions (user_id, description, amount, type, category, frequency, next_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (session['user_id'], description, amount, trans_type, category, frequency, next_date))
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Recurring transaction set: {description} — {frequency}', 'success')
    return redirect(url_for('recurring.recurring'))


@recurring_bp.route('/delete_recurring/<int:tx_id>')
def delete_recurring(tx_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM recurring_transactions WHERE id = %s AND user_id = %s",
                   (tx_id, session['user_id']))
    db.commit()
    cursor.close()
    db.close()
    
    flash('Recurring transaction deleted.', 'success')
    return redirect(url_for('recurring.recurring'))


@recurring_bp.route('/process_recurring')
def process_recurring():
    """Process all due recurring transactions — call via cron or manual trigger"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    today = date.today()
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT * FROM recurring_transactions WHERE next_date <= %s AND is_active = 1
    """, (today,))
    due = cursor.fetchall()
    
    processed = 0
    for tx in due:
        # Insert the transaction
        cursor.execute("""
            INSERT INTO transactions (user_id, description, amount, type, category, transaction_date)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (tx['user_id'], tx['description'], tx['amount'], tx['type'], tx['category'], today))
        
        # Calculate next date
        next_date = get_next_date(tx['next_date'], tx['frequency'])
        cursor.execute("UPDATE recurring_transactions SET next_date = %s WHERE id = %s",
                      (next_date, tx['id']))
        processed += 1
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'{processed} recurring transactions processed.', 'success')
    return redirect(url_for('recurring.recurring'))