from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date, timedelta
from models.database import get_db

fiscal_bp = Blueprint('fiscal', __name__)

@fiscal_bp.route('/fiscal-year')
def fiscal_year():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('role') not in ['admin', 'owner']:
        flash('Only admins can manage fiscal years.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT * FROM fiscal_years WHERE user_id = %s ORDER BY year DESC
    """, (session['user_id'],))
    years = cursor.fetchall()
    
    # Get retained earnings
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total FROM retained_earnings WHERE user_id = %s
    """, (session['user_id'],))
    retained = float(cursor.fetchone()['total'] or 0)
    
    # Current year net income
    today = date.today()
    current_year_start = date(today.year, 1, 1)
    
    cursor.execute("""
        SELECT SUM(amount) as total FROM (
            SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date >= %s
            UNION ALL
            SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date >= %s
        ) AS revenue
    """, (business_id, current_year_start, business_id, current_year_start))
    revenue = float(cursor.fetchone()['total'] or 0)
    
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date >= %s
    """, (business_id, current_year_start))
    expenses = float(cursor.fetchone()['total'] or 0)
    
    net_income = revenue - expenses
    
    cursor.close()
    db.close()
    
    return render_template('fiscal_year.html',
                         username=session['username'],
                         years=years,
                         retained=retained,
                         net_income=net_income,
                         current_year=today.year,
                         today=today.isoformat())


@fiscal_bp.route('/close_year', methods=['POST'])
def close_year():
    if 'user_id' not in session or session.get('role') not in ['admin', 'owner']:
        return redirect(url_for('auth.login'))
    
    year = int(request.form['year'])
    end_date = request.form.get('end_date', f'{year}-12-31')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    # Calculate net income
    start_date = f'{year}-01-01'
    
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total FROM (
            SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date BETWEEN %s AND %s
            UNION ALL
            SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
        ) AS revenue
    """, (business_id, start_date, end_date, business_id, start_date, end_date))
    revenue = float(cursor.fetchone()['total'] or 0)
    
    cursor.execute("""
        SELECT SUM(t.amount) as total FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date BETWEEN %s AND %s
    """, (business_id, start_date, end_date))
    expenses = float(cursor.fetchone()['total'] or 0)
    
    net_income = revenue - expenses
    
    # Create fiscal year record
    cursor.execute("""
        INSERT INTO fiscal_years (user_id, year, start_date, end_date, status, closed_at, net_income)
        VALUES (%s, %s, %s, %s, 'closed', NOW(), %s)
    """, (session['user_id'], year, start_date, end_date, net_income))
    
    # Transfer net income to retained earnings
    cursor.execute("""
        INSERT INTO retained_earnings (user_id, amount, entry_date, description)
        VALUES (%s, %s, CURDATE(), %s)
    """, (session['user_id'], net_income, f'Net income for fiscal year {year}'))
    
    # Create journal entry for closing
    if session.get('plan') in ['pro', 'enterprise']:
        # Get account IDs
        cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '3000'")  # Retained Earnings
        retained_account = cursor.fetchone()
        
        if retained_account:
            cursor.execute("""
                INSERT INTO journal_entries (user_id, entry_date, description)
                VALUES (%s, %s, %s)
            """, (session['user_id'], end_date, f'Fiscal year {year} closing - close income/expense to retained earnings'))
            entry_id = cursor.lastrowid
            
            # Close revenue to retained earnings
            if revenue > 0:
                cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '4000'")
                revenue_account = cursor.fetchone()
                if revenue_account:
                    cursor.execute("""
                        INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
                        VALUES (%s, %s, %s, 0)
                    """, (entry_id, revenue_account['id'], revenue))
            
            # Close expenses to retained earnings
            if expenses > 0:
                cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '5000'")
                expense_account = cursor.fetchone()
                if expense_account:
                    cursor.execute("""
                        INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
                        VALUES (%s, %s, 0, %s)
                    """, (entry_id, expense_account['id'], expenses))
            
            # Net to retained earnings
            cursor.execute("""
                INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
                VALUES (%s, %s, %s, %s)
            """, (entry_id, retained_account['id'], 
                  0 if net_income >= 0 else abs(net_income),
                  net_income if net_income >= 0 else 0))
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Fiscal year {year} closed! Net income ₱{net_income:,.2f} transferred to Retained Earnings.', 'success')
    return redirect(url_for('fiscal.fiscal_year'))