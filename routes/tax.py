from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from models.database import get_db

tax_bp = Blueprint('tax', __name__)

@tax_bp.route('/tax')
def tax():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    today = date.today()
    first_of_month = today.replace(day=1)
    last_month = first_of_month - timedelta(days=1)
    last_month_start = last_month.replace(day=1)
    
    # Get user's VAT status
    cursor.execute("SELECT vat_registered FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    is_vat = user['vat_registered'] if user else True
    
    # Output VAT (from sales/income)
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total FROM (
            SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date BETWEEN %s AND %s
            UNION ALL
            SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
        ) AS revenue
    """, (business_id, last_month_start, last_month, business_id, last_month_start, last_month))
    gross_income = float(cursor.fetchone()['total'] or 0)
    
    # Input VAT (from expenses)
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, last_month_start, last_month))
    gross_expenses = float(cursor.fetchone()['total'] or 0)
    
    # VAT calculations
    if is_vat:
        output_vat = gross_income * 0.12
        input_vat = gross_expenses * 0.12
        vat_payable = output_vat - input_vat
        percentage_tax = 0
    else:
        output_vat = 0
        input_vat = 0
        vat_payable = 0
        percentage_tax = gross_income * 0.03
    
    # Withholding tax on expenses (estimate at 5%)
    withholding_payable = gross_expenses * 0.05
    
    # Get previous filings
    cursor.execute("""
        SELECT * FROM tax_filings WHERE user_id = %s ORDER BY period DESC LIMIT 12
    """, (session['user_id'],))
    filings = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('tax.html',
                         username=session['username'],
                         is_vat=is_vat,
                         gross_income=gross_income,
                         gross_expenses=gross_expenses,
                         output_vat=output_vat,
                         input_vat=input_vat,
                         vat_payable=vat_payable,
                         percentage_tax=percentage_tax,
                         withholding_payable=withholding_payable,
                         period=last_month.strftime('%B %Y'),
                         filings=filings,
                         today=today.isoformat())


@tax_bp.route('/file_tax', methods=['POST'])
def file_tax():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    form_type = request.form['form_type']
    period = request.form['period']
    gross_amount = float(request.form['gross_amount'])
    tax_amount = float(request.form['tax_amount'])
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO tax_filings (user_id, form_type, period, gross_amount, tax_amount, status)
        VALUES (%s, %s, %s, %s, %s, 'filed')
    """, (session['user_id'], form_type, period, gross_amount, tax_amount))
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'{form_type} for {period} filed — Tax: ₱{tax_amount:,.2f}', 'success')
    return redirect(url_for('tax.tax'))