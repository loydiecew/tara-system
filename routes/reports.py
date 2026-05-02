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
            SELECT COALESCE(SUM(a.current_value), 0) as total FROM assets a
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