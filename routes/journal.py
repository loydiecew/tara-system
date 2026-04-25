from flask import Blueprint, render_template, session, redirect, url_for
from models.database import get_db

journal_bp = Blueprint('journal', __name__)

@journal_bp.route('/journal')
def journal():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get cash transactions
    cursor.execute("""
        SELECT 
            transaction_date as date,
            description,
            category,
            type,
            amount,
            'cash' as source
        FROM transactions 
        WHERE user_id = %s
    """, (session['user_id'],))
    cash_transactions = cursor.fetchall()
    
    # Get sales
    cursor.execute("""
        SELECT 
            sale_date as date,
            CONCAT('Sale to ', customer_name) as description,
            'Sales' as category,
            'income' as type,
            amount,
            'sales' as source
        FROM sales 
        WHERE user_id = %s
    """, (session['user_id'],))
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