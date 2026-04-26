from flask import Blueprint, render_template, session, redirect, url_for
from models.database import get_db

journal_bp = Blueprint('journal', __name__)

@journal_bp.route('/journal')
def journal():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Cash transactions
    cursor.execute("""
        SELECT 
            t.transaction_date as date,
            t.description,
            t.category,
            t.type,
            t.amount,
            'cash' as source
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s
    """, (session['business_id'],))
    cash_transactions = cursor.fetchall()
    
    # Sales
    cursor.execute("""
        SELECT 
            s.sale_date as date,
            CONCAT('Sale to ', s.customer_name) as description,
            'Sales' as category,
            'income' as type,
            s.amount,
            'sales' as source
        FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s
    """, (session['business_id'],))
    sales_transactions = cursor.fetchall()
    
    # Combine both lists
    all_transactions = cash_transactions + sales_transactions
    
    # Sort by date (newest first)
    all_transactions.sort(key=lambda x: x['date'], reverse=True)
    
    # Calculate totals
    total_income = sum(t['amount'] for t in all_transactions if t['type'] == 'income')
    total_expense = sum(t['amount'] for t in all_transactions if t['type'] == 'expense')
    net = total_income - total_expense
    
    cursor.close()
    db.close()
    
    return render_template('journal.html',
                         username=session['username'],
                         transactions=all_transactions,
                         total_income=total_income,
                         total_expense=total_expense,
                         net=net)