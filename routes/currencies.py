from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from models.database import get_db

currencies_bp = Blueprint('currencies', __name__)

@currencies_bp.route('/currencies')
def currencies():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM currencies ORDER BY code")
    all_currencies = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('currencies.html',
                         username=session['username'],
                         currencies=all_currencies)


@currencies_bp.route('/update_rate', methods=['POST'])
def update_rate():
    if 'user_id' not in session or session.get('role') not in ['admin', 'owner']:
        return redirect(url_for('auth.login'))
    
    code = request.form['code']
    rate = float(request.form['rate'])
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE currencies SET rate_to_php = %s WHERE code = %s AND code != 'PHP'",
                   (rate, code))
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Exchange rate for {code} updated to ₱{rate:,.4f}', 'success')
    return redirect(url_for('currencies.currencies'))