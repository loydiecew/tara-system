from flask import Blueprint, render_template, session, redirect, url_for, request
from datetime import date
from models.database import get_db

all_transactions_bp = Blueprint('all_transactions', __name__)

@all_transactions_bp.route('/all-transactions')
def all_transactions():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    # Only admin, owner, manager can access
    if session.get('role') not in ['admin', 'owner', 'manager', 'cashier']:
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get filter parameters
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    source = request.args.get('source', 'all')
    trans_type = request.args.get('type', 'all')
    search = request.args.get('search', '')
    
    all_items = []
    
    # Build base WHERE clause
    def build_date_clause(date_field, params):
        clauses = ""
        if date_from:
            clauses += f" AND {date_field} >= %s"
            params.append(date_from)
        if date_to:
            clauses += f" AND {date_field} <= %s"
            params.append(date_to)
        if search:
            clauses += " AND (description LIKE %s OR customer_name LIKE %s OR supplier_name LIKE %s)"
            params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
        return clauses
    
    # ========== CASH TRANSACTIONS ==========
    if source in ['all', 'cash']:
        query = """
            SELECT 
                t.transaction_date as date,
                t.description,
                t.category,
                t.type,
                t.amount,
                'Cash' as source_module,
                'cash' as source_type
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.deleted_at IS NULL
        """
        params = [business_id]
        
        if trans_type != 'all':
            query += " AND t.type = %s"
            params.append(trans_type)
        
        query += build_date_clause('t.transaction_date', params)
        query += " ORDER BY t.transaction_date DESC LIMIT 200"
        
        cursor.execute(query, params)
        all_items.extend(cursor.fetchall())
    
    # ========== SALES ==========
    if source in ['all', 'sales'] and trans_type in ['all', 'income']:
        query = """
            SELECT 
                s.sale_date as date,
                CONCAT('Sale to ', s.customer_name) as description,
                'Sales' as category,
                'income' as type,
                s.amount,
                'Sales' as source_module,
                'sales' as source_type
            FROM sales s
            JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.deleted_at IS NULL
        """
        params = [business_id]
        query += build_date_clause('s.sale_date', params)
        query += " ORDER BY s.sale_date DESC LIMIT 200"
        
        cursor.execute(query, params)
        all_items.extend(cursor.fetchall())
    
    # ========== AR PAYMENTS ==========
    if source in ['all', 'ar'] and trans_type in ['all', 'income']:
        query = """
            SELECT 
                p.payment_date as date,
                CONCAT('Payment from ', c.name, ' - ', COALESCE(i.invoice_number, CONCAT('INV-', i.id))) as description,
                'AR Payment' as category,
                'income' as type,
                p.amount,
                'AR' as source_module,
                'ar' as source_type
            FROM payments p
            JOIN invoices i ON p.invoice_id = i.id
            JOIN customers c ON i.customer_id = c.id
            JOIN users u ON p.user_id = u.id
            WHERE u.business_id = %s AND i.deleted_at IS NULL
        """
        params = [business_id]
        query += build_date_clause('p.payment_date', params)
        query += " ORDER BY p.payment_date DESC LIMIT 200"
        
        cursor.execute(query, params)
        all_items.extend(cursor.fetchall())
    
    # ========== AP PAYMENTS ==========
    if source in ['all', 'ap'] and trans_type in ['all', 'expense']:
        query = """
            SELECT 
                p.payment_date as date,
                CONCAT('Payment to ', s.name, ' - ', COALESCE(b.bill_number, CONCAT('BILL-', b.id))) as description,
                'AP Payment' as category,
                'expense' as type,
                p.amount,
                'AP' as source_module,
                'ap' as source_type
            FROM payments p
            JOIN bills b ON p.bill_id = b.id
            JOIN suppliers s ON b.supplier_id = s.id
            JOIN users u ON p.user_id = u.id
            WHERE u.business_id = %s AND b.deleted_at IS NULL
        """
        params = [business_id]
        query += build_date_clause('p.payment_date', params)
        query += " ORDER BY p.payment_date DESC LIMIT 200"
        
        cursor.execute(query, params)
        all_items.extend(cursor.fetchall())
    
    # Sort all by date
    all_items.sort(key=lambda x: str(x['date']), reverse=True)
    
    # Calculate totals
    total_income = sum(item['amount'] for item in all_items if item['type'] == 'income')
    total_expense = sum(item['amount'] for item in all_items if item['type'] == 'expense')
    
    cursor.close()
    db.close()
    
    return render_template('all_transactions.html',
                         username=session['username'],
                         transactions=all_items,
                         total_income=total_income,
                         total_expense=total_expense,
                         net=total_income - total_expense,
                         date_from=date_from,
                         date_to=date_to,
                         source_filter=source,
                         type_filter=trans_type,
                         search=search,
                         today=date.today().isoformat())