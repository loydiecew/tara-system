from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date
from models.database import get_db
from models.access_control import check_module_access

orders_bp = Blueprint('orders', __name__)

# ========== PURCHASE ORDERS ==========

@orders_bp.route('/purchase-orders')
def purchase_orders():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    if not check_module_access('purchase_orders'): return redirect(url_for('dashboard.dashboard'))

    if session.get('role') not in ['admin', 'owner', 'manager']:
        flash('Access restricted.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    # Get all POs
    cursor.execute("""
        SELECT po.*, s.name as supplier_name
        FROM purchase_orders po
        LEFT JOIN suppliers s ON po.supplier_id = s.id
        JOIN users u ON po.user_id = u.id
        WHERE u.business_id = %s
        ORDER BY po.order_date DESC
    """, (business_id,))
    orders = cursor.fetchall()
    
     # Get products for dropdown
    cursor.execute("""
        SELECT p.id, p.name, p.cogs, p.price, p.quantity FROM products p
        JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.deleted_at IS NULL
        ORDER BY p.name
    """, (business_id,))
    products = cursor.fetchall()

    # Get suppliers for dropdown
    cursor.execute("""
        SELECT s.id, s.name FROM suppliers s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.deleted_at IS NULL
    """, (business_id,))
    suppliers = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('purchase_orders.html',
                         username=session['username'],
                         orders=orders,
                         suppliers=suppliers,
                         products=products,
                         today=date.today().isoformat())

@orders_bp.route('/add_po', methods=['POST'])
def add_po():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    supplier_id = request.form.get('supplier_id') or None
    order_date = request.form.get('order_date', date.today())
    expected_date = request.form.get('expected_date', '')
    notes = request.form.get('notes', '')
    
    # Get items from form
    product_names = request.form.getlist('product_name[]')
    quantities = request.form.getlist('quantity[]')
    unit_prices = request.form.getlist('unit_price[]')
    
    total = 0
    items = []
    for i in range(len(product_names)):
        if product_names[i].strip():
            qty = int(quantities[i])
            price = float(unit_prices[i])
            total += qty * price
            items.append({'name': product_names[i].strip(), 'qty': qty, 'price': price})
    
    if not items:
        flash('Add at least one item', 'error')
        return redirect(url_for('orders.purchase_orders'))
    
    db = get_db()
    cursor = db.cursor()
    
    po_number = f"PO-{date.today().strftime('%Y%m%d')}-{session['user_id']}-{cursor.lastrowid if hasattr(cursor, 'lastrowid') else '1'}"
    
    cursor.execute("""
        INSERT INTO purchase_orders (user_id, supplier_id, po_number, order_date, expected_date, total_amount, notes, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'ordered')
    """, (session['user_id'], supplier_id, po_number, order_date, 
          expected_date if expected_date else None, total, notes))
    po_id = cursor.lastrowid
    
    for item in items:
        cursor.execute("""
            INSERT INTO po_items (po_id, product_name, quantity, unit_price)
            VALUES (%s, %s, %s, %s)
        """, (po_id, item['name'], item['qty'], item['price']))
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Purchase Order #{po_number} created!', 'success')
    return redirect(url_for('orders.purchase_orders'))


@orders_bp.route('/receive_po/<int:po_id>')
def receive_po(po_id):
    """Mark PO as received: update inventory + create AP bill"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT po.*, s.name as supplier_name
        FROM purchase_orders po
        LEFT JOIN suppliers s ON po.supplier_id = s.id
        WHERE po.id = %s AND po.user_id = %s
    """, (po_id, session['user_id']))
    po = cursor.fetchone()
    
    if not po or po['status'] != 'ordered':
        cursor.close()
        db.close()
        flash('PO not found or already received', 'error')
        return redirect(url_for('orders.purchase_orders'))
    
    # Get PO items
    cursor.execute("SELECT * FROM po_items WHERE po_id = %s", (po_id,))
    items = cursor.fetchall()
    
    # Update inventory and create AP bill
    for item in items:
        # Add to inventory
        cursor.execute("""
            INSERT INTO products (user_id, name, quantity, price, cogs, category)
            VALUES (%s, %s, %s, %s, %s, 'Purchased')
            ON DUPLICATE KEY UPDATE quantity = quantity + %s
        """, (session['user_id'], item['product_name'], item['quantity'], 
              item['unit_price'], item['unit_price'], item['quantity']))
    
    # Create AP bill
    supplier_name = po['supplier_name'] or 'Supplier'
    cursor.execute("""
        INSERT INTO bills (user_id, supplier_id, bill_number, amount, description, due_date, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'unpaid')
    """, (
        session['user_id'],
        po['supplier_id'],
        f"BILL-{po['po_number']}",
        po['total_amount'],
        f"Purchase Order #{po['po_number']} - {supplier_name}",
        date.today()
    ))
    
    # Update PO status
    cursor.execute("UPDATE purchase_orders SET status = 'received' WHERE id = %s", (po_id,))
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'PO #{po["po_number"]} received! Inventory updated, bill created.', 'success')
    return redirect(url_for('orders.purchase_orders'))


# ========== SALES ORDERS ==========

@orders_bp.route('/sales-orders')
def sales_orders():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))  

    if not check_module_access('sales_orders'): return redirect(url_for('dashboard.dashboard'))

    if session.get('role') not in ['admin', 'owner', 'manager']:
        flash('Access restricted.', 'error')
        return redirect(url_for('dashboard.dashboard'))

    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])

    cursor.execute("""
        SELECT p.id, p.name, p.price, p.quantity FROM products p
        JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.deleted_at IS NULL
        ORDER BY p.name
    """, (business_id,))
    products = cursor.fetchall()

    cursor.execute("""
        SELECT so.*, c.name as customer_name
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        JOIN users u ON so.user_id = u.id
        WHERE u.business_id = %s
        ORDER BY so.order_date DESC
    """, (business_id,))
    orders = cursor.fetchall()
    
    cursor.execute("""
        SELECT c.id, c.name FROM customers c
        JOIN users u ON c.user_id = u.id
        WHERE u.business_id = %s AND c.deleted_at IS NULL
    """, (business_id,))
    customers = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('sales_orders.html',
                         username=session['username'],
                         orders=orders,
                         customers=customers,
                         products=products,
                         today=date.today().isoformat())


@orders_bp.route('/add_so', methods=['POST'])
def add_so():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    customer_id = request.form.get('customer_id') or None
    order_date = request.form.get('order_date', date.today())
    delivery_date = request.form.get('delivery_date', '')
    notes = request.form.get('notes', '')
    
    product_names = request.form.getlist('product_name[]')
    quantities = request.form.getlist('quantity[]')
    unit_prices = request.form.getlist('unit_price[]')
    
    total = 0
    items = []
    for i in range(len(product_names)):
        if product_names[i].strip():
            qty = int(quantities[i])
            price = float(unit_prices[i])
            total += qty * price
            items.append({'name': product_names[i].strip(), 'qty': qty, 'price': price})
    
    if not items:
        flash('Add at least one item', 'error')
        return redirect(url_for('orders.sales_orders'))
    
    db = get_db()
    cursor = db.cursor()
    
    so_number = f"SO-{date.today().strftime('%Y%m%d')}-{session['user_id']}"
    
    delivery_date = request.form.get('delivery_date', '')

    db = get_db()
    cursor = db.cursor()
    
    so_number = f"SO-{date.today().strftime('%Y%m%d')}-{session['user_id']}"
    
    cursor.execute("""
        INSERT INTO sales_orders (user_id, customer_id, so_number, order_date, delivery_date, total_amount, notes, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'confirmed')
    """, (session['user_id'], customer_id, so_number, order_date,          
        delivery_date if delivery_date else None, total, notes))
    so_id = cursor.lastrowid
    
    for item in items:
        cursor.execute("""
            INSERT INTO so_items (so_id, product_name, quantity, unit_price)
            VALUES (%s, %s, %s, %s)
        """, (so_id, item['name'], item['qty'], item['price']))
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Sales Order #{so_number} created!', 'success')
    return redirect(url_for('orders.sales_orders'))


@orders_bp.route('/deliver_so/<int:so_id>')
def deliver_so(so_id):
    """Mark SO as delivered: deduct inventory + create AR invoice"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT so.*, c.name as customer_name
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        WHERE so.id = %s AND so.user_id = %s
    """, (so_id, session['user_id']))
    so = cursor.fetchone()
    
    if not so or so['status'] != 'confirmed':
        cursor.close()
        db.close()
        flash('SO not found or already delivered', 'error')
        return redirect(url_for('orders.sales_orders'))
    
    # Get SO items and deduct inventory
    cursor.execute("SELECT * FROM so_items WHERE so_id = %s", (so_id,))
    items = cursor.fetchall()
    
    for item in items:
        cursor.execute("""
            UPDATE products SET quantity = quantity - %s
            WHERE user_id = %s AND name = %s AND quantity >= %s
        """, (item['quantity'], session['user_id'], item['product_name'], item['quantity']))
    
    # Create AR invoice
    customer_name = so['customer_name'] or 'Customer'
    cursor.execute("""
        INSERT INTO invoices (user_id, customer_id, invoice_number, amount, description, due_date, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'unpaid')
    """, (
        session['user_id'],
        so['customer_id'],
        f"INV-{so['so_number']}",
        so['total_amount'],
        f"Sales Order #{so['so_number']} - {customer_name}",
        date.today()
    ))
    
    cursor.execute("UPDATE sales_orders SET status = 'delivered' WHERE id = %s", (so_id,))
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'SO #{so["so_number"]} delivered! Inventory deducted, invoice created.', 'success')
    return redirect(url_for('orders.sales_orders'))

@orders_bp.route('/email_po/<int:po_id>')
def email_po(po_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT po.*, s.name as supplier_name, s.email as supplier_email
        FROM purchase_orders po
        LEFT JOIN suppliers s ON po.supplier_id = s.id
        WHERE po.id = %s AND po.user_id = %s
    """, (po_id, session['user_id']))
    po = cursor.fetchone()
    cursor.close()
    db.close()
    
    if not po or not po.get('supplier_email'):
        flash('Supplier has no email address.', 'error')
        return redirect(url_for('orders.purchase_orders'))
    
    from models.email_service import send_email
    subject = f"Purchase Order {po['po_number']} from {session.get('business_name', 'TARA')}"
    body = f"""<p>Dear {po['supplier_name']},</p>
    <p>Please find our purchase order below:</p>
    <p><strong>PO Number:</strong> {po['po_number']}<br>
    <strong>Date:</strong> {po['order_date']}<br>
    <strong>Expected Delivery:</strong> {po.get('expected_date', 'N/A')}<br>
    <strong>Total:</strong> ₱{float(po['total_amount']):,.2f}</p>
    <p>Thank you.</p>"""
    
    success, msg = send_email(po['supplier_email'], subject, body)
    flash('PO emailed to supplier!' if success else f'Failed: {msg}', 'success' if success else 'error')
    return redirect(url_for('orders.purchase_orders'))

@orders_bp.route('/email_so/<int:so_id>')
def email_so(so_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT so.*, c.name as customer_name, c.email as customer_email
        FROM sales_orders so
        LEFT JOIN customers c ON so.customer_id = c.id
        WHERE so.id = %s AND so.user_id = %s
    """, (so_id, session['user_id']))
    so = cursor.fetchone()
    cursor.close()
    db.close()
    
    if not so or not so.get('customer_email'):
        flash('Customer has no email address.', 'error')
        return redirect(url_for('orders.sales_orders'))
    
    from models.email_service import send_email
    subject = f"Sales Order {so['so_number']} from {session.get('business_name', 'TARA')}"
    body = f"""<p>Dear {so['customer_name']},</p>
    <p>Thank you for your order! Here are the details:</p>
    <p><strong>SO Number:</strong> {so['so_number']}<br>
    <strong>Date:</strong> {so['order_date']}<br>
    <strong>Delivery Date:</strong> {so.get('delivery_date', 'N/A')}<br>
    <strong>Total:</strong> ₱{float(so['total_amount']):,.2f}</p>
    <p>We'll notify you once it's delivered.</p>"""
    
    success, msg = send_email(so['customer_email'], subject, body)
    flash('SO emailed to customer!' if success else f'Failed: {msg}', 'success' if success else 'error')
    return redirect(url_for('orders.sales_orders'))