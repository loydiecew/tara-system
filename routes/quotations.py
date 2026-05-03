from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date, timedelta
from models.database import get_db
from models.audit import log_audit
from models.email_service import send_quote_email
from models.access_control import check_module_access

quotations_bp = Blueprint('quotations', __name__)

@quotations_bp.route('/quotations')
def quotations():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    if not check_module_access('quotations'): return redirect(url_for('dashboard.dashboard'))

    if session.get('plan') not in ['enterprise']:
        flash('Quotations are available on Enterprise plan only.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT q.*, c.name as customer_name, c.email as customer_email
        FROM quotations q
        LEFT JOIN customers c ON q.customer_id = c.id
        JOIN users u ON q.user_id = u.id
        WHERE u.business_id = %s
        ORDER BY q.quote_date DESC
    """, (business_id,))
    quotes = cursor.fetchall()
    
    cursor.execute("""
        SELECT c.id, c.name FROM customers c
        JOIN users u ON c.user_id = u.id
        WHERE u.business_id = %s AND c.deleted_at IS NULL
    """, (business_id,))
    customers = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('quotations.html',
                         username=session['username'],
                         quotes=quotes,
                         customers=customers,
                         today=date.today().isoformat())


@quotations_bp.route('/add_quote', methods=['POST'])
def add_quote():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('plan') not in ['enterprise']:
        flash('Quotations are available on Enterprise plan only.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    customer_id = request.form.get('customer_id') or None
    quote_date = request.form.get('quote_date', date.today())
    valid_until = request.form.get('valid_until', '')
    notes = request.form.get('notes', '')
    terms = request.form.get('terms', '')
    discount_percent = float(request.form.get('discount_percent', 0))
    discount_amount = float(request.form.get('discount_amount', 0))
    
    product_names = request.form.getlist('product_name[]')
    quantities = request.form.getlist('quantity[]')
    unit_prices = request.form.getlist('unit_price[]')
    descriptions = request.form.getlist('item_description[]')
    
    subtotal = 0
    items = []
    for i in range(len(product_names)):
        if product_names[i].strip():
            qty = int(quantities[i] or 1)
            price = float(unit_prices[i] or 0)
            amount = qty * price
            subtotal += amount
            items.append({
                'name': product_names[i].strip(),
                'qty': qty,
                'price': price,
                'amount': amount,
                'desc': descriptions[i].strip() if i < len(descriptions) else ''
            })
    
    if not items:
        flash('Add at least one item to the quotation.', 'error')
        return redirect(url_for('quotations.quotations'))
    
    total = subtotal - discount_amount
    if discount_percent > 0 and discount_amount == 0:
        discount_amount = subtotal * (discount_percent / 100)
        total = subtotal - discount_amount
    
    db = get_db()
    cursor = db.cursor()
    
    quote_number = f"QTE-{date.today().strftime('%Y%m%d')}-{session['user_id']}"
    
    cursor.execute("""
        INSERT INTO quotations (user_id, customer_id, quote_number, quote_date, valid_until,
                              notes, terms, subtotal, discount_percent, discount_amount, total_amount)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (session['user_id'], customer_id, quote_number, quote_date,
          valid_until if valid_until else None, notes, terms,
          subtotal, discount_percent, discount_amount, total))
    quote_id = cursor.lastrowid
    
    for item in items:
        cursor.execute("""
            INSERT INTO quote_items (quote_id, product_name, description, quantity, unit_price, amount)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (quote_id, item['name'], item['desc'], item['qty'], item['price'], item['amount']))
    
    db.commit()
    log_audit(session['user_id'], session['username'], 'CREATE', 'quotations', 
            quote_id, new_values={'quote_number': quote_number, 'total_amount': total})
    cursor.close()
    db.close()
    
    flash(f'Quotation #{quote_number} created!', 'success')
    return redirect(url_for('quotations.quotations'))


@quotations_bp.route('/update_quote_status/<int:quote_id>/<status>')
def update_quote_status(quote_id, status):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    valid_statuses = ['draft', 'sent', 'accepted', 'converted', 'expired', 'rejected']
    if status not in valid_statuses:
        flash('Invalid status.', 'error')
        return redirect(url_for('quotations.quotations'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM quotations WHERE id = %s AND user_id = %s", 
                   (quote_id, session['user_id']))
    quote = cursor.fetchone()
    
    if not quote:
        cursor.close()
        db.close()
        flash('Quotation not found.', 'error')
        return redirect(url_for('quotations.quotations'))
    
    cursor.execute("UPDATE quotations SET status = %s WHERE id = %s", (status, quote_id))
    log_audit(session['user_id'], session['username'], 'UPDATE', 'quotations', 
            quote_id, old_values={'status': quote['status']}, new_values={'status': status})
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Quotation marked as {status}.', 'success')
    return redirect(url_for('quotations.quotations'))


@quotations_bp.route('/convert_quote/<int:quote_id>')
def convert_quote(quote_id):
    """Convert accepted quote to Sales Order or Invoice"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT q.*, c.name as customer_name
        FROM quotations q
        LEFT JOIN customers c ON q.customer_id = c.id
        WHERE q.id = %s AND q.user_id = %s AND q.status = 'accepted'
    """, (quote_id, session['user_id']))
    quote = cursor.fetchone()
    
    if not quote:
        cursor.close()
        db.close()
        flash('Quotation not found or not accepted yet.', 'error')
        return redirect(url_for('quotations.quotations'))
    
    cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = cursor.fetchall()
    
    # Create Sales Order from quote
    so_number = f"SO-{date.today().strftime('%Y%m%d')}-{session['user_id']}"
    
    cursor.execute("""
        INSERT INTO sales_orders (user_id, customer_id, so_number, order_date, total_amount, notes)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (session['user_id'], quote['customer_id'], so_number, date.today(),
          quote['total_amount'], f"Converted from Quote #{quote['quote_number']}"))
    so_id = cursor.lastrowid
    
    for item in items:
        cursor.execute("""
            INSERT INTO so_items (so_id, product_name, quantity, unit_price)
            VALUES (%s, %s, %s, %s)
        """, (so_id, item['product_name'], item['quantity'], item['unit_price']))
    
    # Mark quote as converted
    cursor.execute("UPDATE quotations SET status = 'converted' WHERE id = %s", (quote_id,))
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Quote converted to Sales Order #{so_number}!', 'success')
    return redirect(url_for('orders.sales_orders'))


@quotations_bp.route('/delete_quote/<int:quote_id>')
def delete_quote(quote_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM quotations WHERE id = %s AND user_id = %s AND status = 'draft'",
                   (quote_id, session['user_id']))
    log_audit(session['user_id'], session['username'], 'DELETE', 'quotations', 
              quote_id, old_values={'quote_number': quote.get('quote_number', '')})
    db.commit()
    cursor.close()
    db.close()
    
    flash('Quotation deleted.', 'success')
    return redirect(url_for('quotations.quotations'))

@quotations_bp.route('/view_quote/<int:quote_id>')
def view_quote(quote_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT q.*, c.name as customer_name, c.email as customer_email, c.phone as customer_phone
        FROM quotations q
        LEFT JOIN customers c ON q.customer_id = c.id
        WHERE q.id = %s AND q.user_id = %s
    """, (quote_id, session['user_id']))
    quote = cursor.fetchone()
    
    if not quote:
        cursor.close()
        db.close()
        flash('Quotation not found.', 'error')
        return redirect(url_for('quotations.quotations'))
    
    cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = cursor.fetchall()
    
    cursor.execute("""
        SELECT business_name FROM users
        WHERE business_id = %s AND role IN ('admin', 'owner')
        LIMIT 1
    """, (business_id,))
    owner = cursor.fetchone()
    
    cursor.close()
    db.close()
    
    return render_template('view_quote.html',
                         quote=quote,
                         items=items,
                         business_name=owner['business_name'] if owner else 'My Business')

@quotations_bp.route('/email_quote/<int:quote_id>')
def email_quote(quote_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT q.*, c.name as customer_name, c.email as customer_email
        FROM quotations q
        LEFT JOIN customers c ON q.customer_id = c.id
        WHERE q.id = %s AND q.user_id = %s
    """, (quote_id, session['user_id']))
    quote = cursor.fetchone()
    
    if not quote or not quote.get('customer_email'):
        flash('Customer has no email address. Please add one first.', 'error')
        return redirect(url_for('quotations.quotations'))
    
    cursor.execute("SELECT business_name FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    db.close()
    
    success, message = send_quote_email(
        quote, 
        quote['customer_name'], 
        quote['customer_email'],
        user['business_name'] or 'My Business'
    )
    
    if success:
        flash(f'Quote emailed to {quote["customer_email"]}!', 'success')
    else:
        flash(f'Failed to send: {message}', 'error')
    
    return redirect(url_for('quotations.quotations'))

@quotations_bp.route('/quote/action/<int:quote_id>/<action>')
def quote_action(quote_id, action):
    """Handle accept/reject from email link (no login required for customer)"""
    if action not in ['accepted', 'rejected']:
        return "Invalid action", 400
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT q.*, c.name as customer_name
        FROM quotations q
        LEFT JOIN customers c ON q.customer_id = c.id
        WHERE q.id = %s AND q.status = 'sent'
    """, (quote_id,))
    quote = cursor.fetchone()
    
    if not quote:
        cursor.close()
        db.close()
        return render_template('quote_action.html', 
                             success=False, 
                             message='Quote not found or already processed.')
    
    new_status = 'accepted' if action == 'accepted' else 'rejected'
    cursor.execute("UPDATE quotations SET status = %s WHERE id = %s", (new_status, quote_id))
    
    log_audit(quote['user_id'], 'Customer', 'UPDATE', 'quotations',
              quote_id, old_values={'status': 'sent'}, new_values={'status': new_status})
    
    db.commit()
    cursor.close()
    db.close()
    
    return render_template('quote_action.html',
                         success=True,
                         action=action,
                         quote=quote,
                         business_name=quote.get('business_name', 'TARA'))