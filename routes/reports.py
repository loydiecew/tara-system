from flask import Blueprint, render_template, request, session, redirect, url_for, flash, make_response
from datetime import date
from models.database import get_db

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/reports')
def reports():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    return render_template('reports.html',
                         username=session['username'],
                         today=date.today().isoformat())


@reports_bp.route('/export/pdf/<report_type>')
def export_pdf(report_type):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    today = date.today()
    
    if report_type == 'profit_loss':
        # Current month P&L
        first_day = today.replace(day=1)
        
        cursor.execute("""
            SELECT SUM(amount) as total FROM (
                SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
                WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date >= %s
                UNION ALL
                SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
                WHERE u.business_id = %s AND s.sale_date >= %s
            ) AS revenue
        """, (business_id, first_day, business_id, first_day))
        revenue = float(cursor.fetchone()['total'] or 0)
        
        cursor.execute("""
            SELECT SUM(t.amount) as total FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date >= %s
        """, (business_id, first_day))
        expenses = float(cursor.fetchone()['total'] or 0)
        
        profit = revenue - expenses
        
        html = render_template('pdf/profit_loss.html',
                             business_name=session.get('business_name', 'My Business'),
                             revenue=revenue, expenses=expenses, profit=profit,
                             month=today.strftime('%B %Y'), today=today)
        
    elif report_type == 'ar_aging':
        cursor.execute("""
            SELECT i.*, c.name as customer_name,
                COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = i.id), 0) as paid
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            JOIN users u ON i.user_id = u.id
            WHERE u.business_id = %s AND i.status IN ('unpaid', 'partially_paid') AND i.deleted_at IS NULL
            ORDER BY i.due_date ASC
        """, (business_id,))
        invoices = cursor.fetchall()
        
        for inv in invoices:
            inv['remaining'] = float(inv['amount']) - float(inv['paid'])
            due = inv['due_date']
            days_overdue = (today - due).days
            if days_overdue <= 0:
                inv['aging'] = 'Current'
            elif days_overdue <= 30:
                inv['aging'] = '1-30 days'
            elif days_overdue <= 60:
                inv['aging'] = '31-60 days'
            else:
                inv['aging'] = '60+ days'
        
        html = render_template('pdf/ar_aging.html',
                             business_name=session.get('business_name', 'My Business'),
                             invoices=invoices, today=today)

    elif report_type == 'balance_sheet':
        cursor.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN t.type = 'income' THEN t.amount ELSE 0 END), 0) -
                COALESCE(SUM(CASE WHEN t.type = 'expense' THEN t.amount ELSE 0 END), 0) as cash
            FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s
        """, (business_id,))
        cash = float(cursor.fetchone()['cash'] or 0)
        
        cursor.execute("""
            SELECT COALESCE(SUM(i.amount), 0) as total FROM invoices i
            JOIN users u ON i.user_id = u.id
            WHERE u.business_id = %s AND i.status IN ('unpaid', 'partially_paid') AND i.deleted_at IS NULL
        """, (business_id,))
        ar = float(cursor.fetchone()['total'] or 0)
        
        cursor.execute("""
            SELECT COALESCE(SUM(p.amount), 0) as total FROM payments p
            JOIN invoices i ON p.invoice_id = i.id JOIN users u ON i.user_id = u.id
            WHERE u.business_id = %s
        """, (business_id,))
        ar_paid = float(cursor.fetchone()['total'] or 0)
        net_ar = ar - ar_paid
        
        cursor.execute("""
            SELECT COALESCE(SUM(p.quantity * p.price), 0) as total FROM products p
            JOIN users u ON p.user_id = u.id WHERE u.business_id = %s AND p.deleted_at IS NULL
        """, (business_id,))
        inventory = float(cursor.fetchone()['total'] or 0)
        
        cursor.execute("""
            SELECT COALESCE(SUM(a.current_value), 0) as total FROM assets a WHERE a.deleted_at IS NULL
            JOIN users u ON a.user_id = u.id WHERE u.business_id = %s AND a.status = 'active'
        """, (business_id,))
        fixed_assets = float(cursor.fetchone()['total'] or 0)
        
        total_assets = cash + net_ar + inventory + fixed_assets
        
        cursor.execute("""
            SELECT COALESCE(SUM(b.amount), 0) as total FROM bills b
            JOIN users u ON b.user_id = u.id
            WHERE u.business_id = %s AND b.status IN ('unpaid', 'partially_paid') AND b.deleted_at IS NULL
        """, (business_id,))
        ap = float(cursor.fetchone()['total'] or 0)
        
        cursor.execute("""
            SELECT COALESCE(SUM(p.amount), 0) as total FROM payments p
            JOIN bills b ON p.bill_id = b.id JOIN users u ON b.user_id = u.id
            WHERE u.business_id = %s
        """, (business_id,))
        ap_paid = float(cursor.fetchone()['total'] or 0)
        net_ap = ap - ap_paid
        total_liabilities = net_ap
        equity = total_assets - total_liabilities
        
        html = render_template('pdf/balance_sheet.html',
                             business_name=session.get('business_name', 'My Business'),
                             cash=cash, net_ar=net_ar, inventory=inventory, fixed_assets=fixed_assets,
                             total_assets=total_assets, net_ap=net_ap, total_liabilities=total_liabilities,
                             equity=equity, today=today)

    elif report_type == 'inventory':
        cursor.execute("""
            SELECT p.* FROM products p
            JOIN users u ON p.user_id = u.id
            WHERE u.business_id = %s AND p.deleted_at IS NULL
            ORDER BY p.name
        """, (business_id,))
        products = cursor.fetchall()
        
        total_value = sum(p['quantity'] * p['price'] for p in products)
        
        html = render_template('pdf/inventory.html',
                             business_name=session.get('business_name', 'My Business'),
                             products=products, total_value=total_value, today=today)
    
    elif report_type == 'sales_report':
        first_day = today.replace(day=1)
        cursor.execute("""
            SELECT s.sale_date, COUNT(*) as count, SUM(s.amount) as total
            FROM sales s JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.sale_date >= %s AND s.deleted_at IS NULL
            GROUP BY s.sale_date ORDER BY s.sale_date DESC
        """, (business_id, first_day))
        daily_sales = cursor.fetchall()
        total_sales = sum(float(d['total']) for d in daily_sales)
        html = render_template('pdf/sales_report.html',
                             business_name=session.get('business_name', 'My Business'),
                             daily_sales=daily_sales, total_sales=total_sales,
                             month=today.strftime('%B %Y'), today=today)

    elif report_type == 'expense_report':
        first_day = today.replace(day=1)
        cursor.execute("""
            SELECT t.category, COUNT(*) as count, SUM(t.amount) as total
            FROM transactions t JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.type = 'expense' AND t.transaction_date >= %s AND t.deleted_at IS NULL
            GROUP BY t.category ORDER BY total DESC
        """, (business_id, first_day))
        expense_categories = cursor.fetchall()
        total_expenses = sum(float(e['total']) for e in expense_categories)
        html = render_template('pdf/expense_report.html',
                             business_name=session.get('business_name', 'My Business'),
                             expense_categories=expense_categories, total_expenses=total_expenses,
                             month=today.strftime('%B %Y'), today=today)

    elif report_type == 'tax_summary':
        first_day = today.replace(day=1)
        cursor.execute("""
            SELECT SUM(amount) as total FROM (
                SELECT t.amount FROM transactions t JOIN users u ON t.user_id = u.id
                WHERE u.business_id = %s AND t.type = 'income' AND t.transaction_date >= %s
                UNION ALL
                SELECT s.amount FROM sales s JOIN users u ON s.user_id = u.id
                WHERE u.business_id = %s AND s.sale_date >= %s
            ) AS revenue
        """, (business_id, first_day, business_id, first_day))
        total_revenue = float(cursor.fetchone()['total'] or 0)
        vat_payable = total_revenue * 0.12
        percentage_tax = total_revenue * 0.03
        html = render_template('pdf/tax_summary.html',
                             business_name=session.get('business_name', 'My Business'),
                             total_revenue=total_revenue, vat_payable=vat_payable,
                             percentage_tax=percentage_tax, month=today.strftime('%B %Y'), today=today)

    elif report_type == 'customer_statement':
        cursor.execute("""
            SELECT c.id as customer_id, c.name as customer_name,
                   i.id as invoice_id, i.invoice_number, i.amount as invoice_amount,
                   i.due_date, i.status,
                   COALESCE(SUM(p.amount), 0) as paid
            FROM customers c
            JOIN invoices i ON c.id = i.customer_id
            LEFT JOIN payments p ON i.id = p.invoice_id
            JOIN users u ON i.user_id = u.id
            WHERE u.business_id = %s AND i.deleted_at IS NULL AND c.deleted_at IS NULL
            GROUP BY c.id, i.id ORDER BY c.name, i.due_date DESC
        """, (business_id,))
        statements = cursor.fetchall()
        html = render_template('pdf/customer_statement.html',
                             business_name=session.get('business_name', 'My Business'),
                             statements=statements, today=today)

    elif report_type == 'supplier_statement':
        cursor.execute("""
            SELECT s.id as supplier_id, s.name as supplier_name,
                   b.id as bill_id, b.bill_number, b.amount as bill_amount,
                   b.due_date, b.status,
                   COALESCE(SUM(p.amount), 0) as paid
            FROM suppliers s
            JOIN bills b ON s.id = b.supplier_id
            LEFT JOIN payments p ON b.id = p.bill_id
            JOIN users u ON b.user_id = u.id
            WHERE u.business_id = %s AND b.deleted_at IS NULL AND s.deleted_at IS NULL
            GROUP BY s.id, b.id ORDER BY s.name, b.due_date DESC
        """, (business_id,))
        supplier_statements = cursor.fetchall()
        html = render_template('pdf/supplier_statement.html',
                             business_name=session.get('business_name', 'My Business'),
                             supplier_statements=supplier_statements, today=today)

    elif report_type == 'trial_balance':
        cursor.execute("""
            SELECT jl.account_id, coa.code as account_code, coa.name as account_name,
                   coa.type as account_type,
                   COALESCE(SUM(jl.debit), 0) as total_debit,
                   COALESCE(SUM(jl.credit), 0) as total_credit
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN chart_of_accounts coa ON jl.account_id = coa.id
            JOIN users u ON je.user_id = u.id
            WHERE u.business_id = %s
            GROUP BY jl.account_id, coa.code, coa.name, coa.type
            ORDER BY coa.code
        """, (business_id,))
        trial_balance = cursor.fetchall()
        total_debits = sum(float(t['total_debit']) for t in trial_balance)
        total_credits = sum(float(t['total_credit']) for t in trial_balance)
        html = render_template('pdf/trial_balance.html',
                             business_name=session.get('business_name', 'My Business'),
                             trial_balance=trial_balance, total_debits=total_debits,
                             total_credits=total_credits, today=today)

    else:
        flash('Invalid report type.', 'error')
        return redirect(url_for('reports.reports'))
    
    cursor.close()
    db.close()
    
    # Generate PDF
    from weasyprint import HTML
    pdf = HTML(string=html).write_pdf()
    
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={report_type}_{today.strftime("%Y%m%d")}.pdf'
    return response