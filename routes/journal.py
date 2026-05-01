from flask import Blueprint, render_template, session, redirect, url_for, request
from datetime import date
from models.database import get_db

journal_bp = Blueprint('journal', __name__)

@journal_bp.route('/journal')
def journal():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get filter parameters from URL
    type_filter = request.args.get('type', 'all')
    source_filter = request.args.get('source', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    search = request.args.get('search', '')
    
    # Initialize collections
    cash_transactions = []
    sales_transactions = []
    
    # ========== CASH TRANSACTIONS ==========
    # Only fetch if source_filter is 'all' or 'cash'
    if source_filter == 'all' or source_filter == 'cash':
        cash_query = """
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
        """
        params = [business_id]
        
        # Apply type filter
        if type_filter == 'income':
            cash_query += " AND t.type = 'income'"
        elif type_filter == 'expense':
            cash_query += " AND t.type = 'expense'"
        # if 'all', no type filter
        
        # Apply search filter (case insensitive)
        if search:
            cash_query += " AND t.description LIKE %s"
            params.append(f'%{search}%')
        
        # Apply date filters
        if date_from:
            cash_query += " AND t.transaction_date >= %s"
            params.append(date_from)
        if date_to:
            cash_query += " AND t.transaction_date <= %s"
            params.append(date_to)
        
        cash_query += " ORDER BY t.transaction_date DESC"
        
        cursor.execute(cash_query, params)
        cash_transactions = cursor.fetchall()
    
    # ========== SALES TRANSACTIONS ==========
    # Only fetch if source_filter is 'all' or 'sales' AND type_filter is not 'expense'
    if (source_filter == 'all' or source_filter == 'sales') and type_filter != 'expense':
        sales_query = """
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
        """
        params = [business_id]
        
        # Apply search filter
        if search:
            sales_query += " AND (s.customer_name LIKE %s OR s.description LIKE %s)"
            params.append(f'%{search}%')
            params.append(f'%{search}%')
        
        # Apply date filters
        if date_from:
            sales_query += " AND s.sale_date >= %s"
            params.append(date_from)
        if date_to:
            sales_query += " AND s.sale_date <= %s"
            params.append(date_to)
        
        sales_query += " ORDER BY s.sale_date DESC"
        
        cursor.execute(sales_query, params)
        sales_transactions = cursor.fetchall()
    
    # Combine and sort
    all_transactions = cash_transactions + sales_transactions
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
                         net=net,
                         type_filter=type_filter,
                         source_filter=source_filter,
                         date_from=date_from,
                         date_to=date_to,
                         search=search,
                         today=date.today().isoformat())

@journal_bp.route('/ledger')
def ledger():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('plan') not in ['pro', 'enterprise']:
        flash('Double-entry journal is available on Pro and Enterprise plans only.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    # Get filters
    search = request.args.get('search', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    query = """
        SELECT je.entry_date, je.description, coa.name as account_name, 
               jl.debit, jl.credit
        FROM journal_entries je
        JOIN journal_lines jl ON je.id = jl.journal_entry_id
        JOIN chart_of_accounts coa ON jl.account_id = coa.id
        JOIN users u ON je.user_id = u.id
        WHERE u.business_id = %s
    """
    params = [business_id]
    
    if search:
        query += " AND (je.description LIKE %s OR coa.name LIKE %s)"
        params.append(f'%{search}%')
        params.append(f'%{search}%')
    
    if date_from:
        query += " AND je.entry_date >= %s"
        params.append(date_from)
    
    if date_to:
        query += " AND je.entry_date <= %s"
        params.append(date_to)
    
    query += " ORDER BY je.entry_date DESC, je.id DESC"
    
    cursor.execute(query, params)
    entries = cursor.fetchall()
    
    total_debits = sum(e['debit'] for e in entries)
    total_credits = sum(e['credit'] for e in entries)
    
    cursor.close()
    db.close()
    
    return render_template('journal_entries.html',
                         username=session['username'],
                         entries=entries,
                         total_debits=total_debits,
                         total_credits=total_credits,
                         today=date.today().isoformat(),
                         search=search,
                         date_from=date_from,
                         date_to=date_to)