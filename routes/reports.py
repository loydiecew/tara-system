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