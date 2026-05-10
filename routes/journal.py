from flask import Blueprint, render_template, session, redirect, url_for, request, flash
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
    
    if session.get('plan') not in ['professional', 'suite']:
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

@journal_bp.route('/trial-balance')
def trial_balance():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('plan') not in ['professional', 'suite']:
        flash('Trial Balance is available on Pro and Enterprise plans.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    query = """
        SELECT 
            coa.code, coa.name as account_name, coa.type as account_type,
            COALESCE(SUM(jl.debit), 0) as total_debit,
            COALESCE(SUM(jl.credit), 0) as total_credit
        FROM chart_of_accounts coa
        LEFT JOIN journal_lines jl ON coa.id = jl.account_id
        LEFT JOIN journal_entries je ON jl.journal_entry_id = je.id
        JOIN users u ON je.user_id = u.id
        WHERE u.business_id = %s
    """
    params = [business_id]
    
    if date_from:
        query += " AND je.entry_date >= %s"
        params.append(date_from)
    if date_to:
        query += " AND je.entry_date <= %s"
        params.append(date_to)
    
    query += " GROUP BY coa.id, coa.code, coa.name, coa.type ORDER BY coa.code"
    
    cursor.execute(query, params)
    accounts = cursor.fetchall()
    
    total_debits = sum(a['total_debit'] for a in accounts)
    total_credits = sum(a['total_credit'] for a in accounts)
    
    cursor.close()
    db.close()
    
    return render_template('trial_balance.html',
                         username=session['username'],
                         accounts=accounts,
                         total_debits=total_debits,
                         total_credits=total_credits,
                         date_from=date_from,
                         date_to=date_to,
                         today=date.today().isoformat())

@journal_bp.route('/income-statement')
def income_statement():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    period = request.args.get('period', 'month')
    today = date.today()
    
    if period == 'month':
        start_date = today.replace(day=1)
        end_date = today
    elif period == 'quarter':
        quarter = (today.month - 1) // 3
        start_date = date(today.year, quarter * 3 + 1, 1)
        end_date = today
    elif period == 'year':
        start_date = date(today.year, 1, 1)
        end_date = today
    else:
        start_date = today - timedelta(days=30)
        end_date = today
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    # Revenue
    cursor.execute("""
        SELECT SUM(amount) as total FROM (
            SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date BETWEEN %s AND %s
            UNION ALL
            SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date BETWEEN %s AND %s
        ) AS revenue
    """, (business_id, start_date, end_date, business_id, start_date, end_date))
    total_revenue = float(cursor.fetchone()['total'] or 0)
    
    # Expenses by category
    cursor.execute("""
        SELECT t.category, SUM(t.amount) as total
        FROM transactions t JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date BETWEEN %s AND %s
        GROUP BY t.category ORDER BY total DESC
    """, (business_id, start_date, end_date))
    expenses = cursor.fetchall()
    
    total_expenses = sum(float(e['total']) for e in expenses)
    net_income = total_revenue - total_expenses
    
    cursor.close()
    db.close()
    
    return render_template('income_statement.html',
                         username=session['username'],
                         total_revenue=total_revenue,
                         expenses=expenses,
                         total_expenses=total_expenses,
                         net_income=net_income,
                         start_date=start_date,
                         end_date=end_date,
                         period=period,
                         today=date.today().isoformat())


@journal_bp.route('/balance-sheet')
def balance_sheet():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    today = date.today()
    
    # Assets — Cash balance
    cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN t.type = 'income' THEN t.amount ELSE 0 END), 0) -
            COALESCE(SUM(CASE WHEN t.type = 'expense' THEN t.amount ELSE 0 END), 0) as cash
        FROM transactions t JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s
    """, (business_id,))
    cash = float(cursor.fetchone()['cash'] or 0)
    
    # AR Outstanding
    cursor.execute("""
        SELECT COALESCE(SUM(i.amount), 0) as total FROM invoices i
        JOIN users u ON i.user_id = u.id
        WHERE u.business_id = %s AND i.status IN ('unpaid', 'partially_paid') AND i.deleted_at IS NULL
    """, (business_id,))
    ar = float(cursor.fetchone()['total'] or 0)
    
    # Less payments received
    cursor.execute("""
        SELECT COALESCE(SUM(p.amount), 0) as total FROM payments p
        JOIN invoices i ON p.invoice_id = i.id
        JOIN users u ON i.user_id = u.id
        WHERE u.business_id = %s
    """, (business_id,))
    ar_paid = float(cursor.fetchone()['total'] or 0)
    net_ar = ar - ar_paid
    
    # Inventory value
    cursor.execute("""
        SELECT COALESCE(SUM(p.quantity * p.price), 0) as total FROM products p
        JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.deleted_at IS NULL
    """, (business_id,))
    inventory = float(cursor.fetchone()['total'] or 0)
    
    # Fixed Assets
    cursor.execute("""
        SELECT COALESCE(SUM(a.current_value), 0) as total FROM assets a
        JOIN users u ON a.user_id = u.id
        WHERE a.deleted_at IS NULL AND u.business_id = %s AND a.status = 'active'
    """, (business_id,))
    fixed_assets = float(cursor.fetchone()['total'] or 0)
    
    total_assets = cash + net_ar + inventory + fixed_assets
    
    # Liabilities — AP Outstanding
    cursor.execute("""
        SELECT COALESCE(SUM(b.amount), 0) as total FROM bills b
        JOIN users u ON b.user_id = u.id
        WHERE u.business_id = %s AND b.status IN ('unpaid', 'partially_paid') AND b.deleted_at IS NULL
    """, (business_id,))
    ap = float(cursor.fetchone()['total'] or 0)
    
    cursor.execute("""
        SELECT COALESCE(SUM(p.amount), 0) as total FROM payments p
        JOIN bills b ON p.bill_id = b.id
        JOIN users u ON b.user_id = u.id
        WHERE u.business_id = %s
    """, (business_id,))
    ap_paid = float(cursor.fetchone()['total'] or 0)
    net_ap = ap - ap_paid
    
    total_liabilities = net_ap
    
    # Equity = Assets - Liabilities
    equity = total_assets - total_liabilities
    
    cursor.close()
    db.close()
    
    return render_template('balance_sheet.html',
                         username=session['username'],
                         cash=cash, net_ar=net_ar, inventory=inventory, fixed_assets=fixed_assets,
                         total_assets=total_assets,
                         net_ap=net_ap, total_liabilities=total_liabilities,
                         equity=equity, today=today.isoformat())