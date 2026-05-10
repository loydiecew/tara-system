from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date
from models.database import get_db
from models.audit import log_audit

sales_bp = Blueprint('sales', __name__)

def create_journal_entry(user_id, entry_date, description, lines):
    from models.database import get_db
    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description) VALUES (%s,%s,%s)",
        (user_id, entry_date, description))
    entry_id = cursor.lastrowid
    for line in lines:
        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,%s,%s)",
            (entry_id, line['account_id'], line.get('debit',0), line.get('credit',0)))
    db.commit()
    cursor.close()
    db.close()
    return entry_id

@sales_bp.route('/sales')
def sales():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT s.* FROM sales s JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.deleted_at IS NULL ORDER BY s.sale_date DESC
    """, (business_id,))
    sales_list = cursor.fetchall()
    
    cursor.execute("""
        SELECT SUM(s.amount) as total FROM sales s JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.deleted_at IS NULL
    """, (business_id,))
    total_sales = float(cursor.fetchone()['total'] or 0)
    
    today = date.today()
    first_day = today.replace(day=1)
    cursor.execute("""
        SELECT SUM(s.amount) as total FROM sales s JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.deleted_at IS NULL AND s.sale_date BETWEEN %s AND %s
    """, (business_id, first_day, today))
    monthly_sales = float(cursor.fetchone()['total'] or 0)
    
    cursor.execute("""
        SELECT p.id, p.name, p.price, p.quantity FROM products p
        JOIN users u ON p.user_id = u.id WHERE u.business_id = %s AND p.deleted_at IS NULL
    """, (business_id,))
    products = cursor.fetchall()
    
    projects = []
    if session.get('plan') in ['professional', 'suite']:
        cursor.execute("""
            SELECT p.id, p.name FROM projects p ON p.deleted_at IS NULL JOIN users u ON p.user_id = u.id
            WHERE u.business_id = %s AND p.status = 'active'
        """, (business_id,))
        projects = cursor.fetchall()
    
    cursor.close()
    db.close()
    return render_template('sales.html', username=session['username'], sales=sales_list,
                         total_sales=total_sales, monthly_sales=monthly_sales,
                         products=products, projects=projects, today=today.isoformat())

@sales_bp.route('/add_sale', methods=['POST'])
def add_sale():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    customer_name = request.form.get('customer_name', 'Walk-in Customer')
    sale_date = request.form.get('sale_date', date.today())
    payment_method = request.form.get('payment_method', 'cash')
    reference_number = request.form.get('reference_number', '')
    served_by = request.form.get('served_by', '')
    project_id = request.form.get('project_id') or None
    
    # Discount fields
    discount_type = request.form.get('discount_type', 'none')  # 'none', 'percent', 'fixed', 'promo'
    discount_value = float(request.form.get('discount_value', 0))
    promo_code = request.form.get('promo_code', '').strip().upper()
    
    # Get items from form
    item_types = request.form.getlist('item_type[]')
    product_ids = request.form.getlist('item_product_id[]')
    item_names = request.form.getlist('item_name[]')
    quantities = request.form.getlist('item_quantity[]')
    unit_prices = request.form.getlist('item_price[]')
    item_discounts = request.form.getlist('item_discount[]')
    
    items = []
    subtotal = 0
    
    for i in range(len(item_types)):
        itype = item_types[i] if i < len(item_types) else 'manual'
        qty = int(quantities[i]) if i < len(quantities) else 1
        price = float(unit_prices[i]) if i < len(unit_prices) else 0
        item_discount = float(item_discounts[i]) if i < len(item_discounts) else 0
        gross_amt = qty * price
        item_discount_amt = gross_amt * (item_discount / 100) if item_discount > 0 else 0
        amt = gross_amt - item_discount_amt
        subtotal += amt
        
        pid = None
        pname = ''
        if itype == 'inventory' and i < len(product_ids) and product_ids[i]:
            pid = int(product_ids[i])
            if i < len(item_names):
                pname = item_names[i]
        elif i < len(item_names):
            pname = item_names[i]
        
        if gross_amt > 0:
            items.append({
                'type': itype, 'product_id': pid, 'name': pname,
                'qty': qty, 'price': price, 'discount_percent': item_discount,
                'discount_amount': item_discount_amt, 'amount': amt
            })
    
    if not items or subtotal <= 0:
        flash('Add at least one item with an amount.', 'error')
        return redirect(url_for('sales.sales'))
    
    # Calculate total discount
    total_discount = 0
    if discount_type == 'percent' and discount_value > 0:
        total_discount = subtotal * (discount_value / 100)
    elif discount_type == 'fixed' and discount_value > 0:
        total_discount = discount_value
    elif discount_type == 'promo' and promo_code:
        # Validate promo code
        db_promo = get_db()
        cursor_promo = db_promo.cursor(dictionary=True)
        cursor_promo.execute("""
            SELECT * FROM promo_codes WHERE user_id = %s AND code = %s AND is_active = 1
            AND (valid_until IS NULL OR valid_until >= %s)
            AND (usage_limit = 0 OR usage_count < usage_limit)
            AND (min_purchase = 0 OR %s >= min_purchase)
        """, (session['user_id'], promo_code, date.today(), subtotal))
        promo = cursor_promo.fetchone()
        if promo:
            if promo['discount_type'] == 'percent':
                total_discount = subtotal * (promo['discount_value'] / 100)
            else:
                total_discount = promo['discount_value']
            cursor_promo.execute("UPDATE promo_codes SET usage_count = usage_count + 1 WHERE id = %s", (promo['id'],))
            db_promo.commit()
        cursor_promo.close()
        db_promo.close()
    
    if total_discount > subtotal:
        total_discount = subtotal
    
    total_amount = subtotal - total_discount
    
    # Build description
    description_parts = []
    for item in items:
        desc = f"{item['qty']}x {item['name']}"
        if item['discount_percent'] > 0:
            desc += f" (-{item['discount_percent']:.0f}%)"
        description_parts.append(desc)
    description = ', '.join(description_parts)
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        INSERT INTO sales (user_id, customer_name, amount, sale_date, description,
                          reference_number, payment_method, served_by, project_id,
                          discount_type, discount_value, discount_amount, promo_code)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (session['user_id'], customer_name, total_amount, sale_date, description,
          reference_number, payment_method, served_by, project_id,
          discount_type, discount_value, total_discount, promo_code))
    sale_id = cursor.lastrowid
    
    for item in items:
        cursor.execute("""
            INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, amount, discount_percent, discount_amount)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (sale_id, item['product_id'], item['name'], item['qty'], item['price'],
              item['amount'], item['discount_percent'], item['discount_amount']))
        
        if item['type'] == 'inventory' and item['product_id']:
            cursor.execute("""
                UPDATE products SET quantity = quantity - %s
                WHERE id = %s AND user_id = %s AND quantity >= %s
            """, (item['qty'], item['product_id'], session['user_id'], item['qty']))
    
    if session.get('plan') in ['professional', 'suite']:
        cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '1000'")
        cash_account = cursor.fetchone()
        cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '4000'")
        revenue_account = cursor.fetchone()
        if cash_account and revenue_account:
            create_journal_entry(session['user_id'], sale_date,
                f"Sale to {customer_name} - {description}",
                [{'account_id': cash_account['id'], 'debit': total_amount, 'credit': 0},
                 {'account_id': revenue_account['id'], 'debit': 0, 'credit': total_amount}])
    
    db.commit()
    cursor.close()
    db.close()
    msg = f'Sale recorded: {len(items)} item(s), ₱{total_amount:,.2f}'
    if total_discount > 0:
        msg += f' (₱{total_discount:,.2f} discount)'
    flash(msg, 'success')
    return redirect(url_for('sales.sales'))

@sales_bp.route('/delete_sale/<int:sale_id>')
def delete_sale(sale_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM sales WHERE id = %s AND user_id = %s", (sale_id, session['user_id']))
    sale = cursor.fetchone()
    if sale and sale.get('deleted_at') is None:
        cursor.execute("UPDATE sales SET deleted_at = NOW() WHERE id = %s AND user_id = %s", (sale_id, session['user_id']))
        db.commit()
        log_audit(session['user_id'], session['username'], 'DELETE', 'sales', sale_id, old_values=sale)
    cursor.close()
    db.close()
    return redirect(url_for('sales.sales'))

@sales_bp.route('/edit_sale/<int:sale_id>', methods=['GET', 'POST'])
def edit_sale(sale_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    if request.method == 'POST':
        cursor.execute("SELECT * FROM sales WHERE id = %s AND user_id = %s AND deleted_at IS NULL", (sale_id, session['user_id']))
        old_sale = cursor.fetchone()
        if not old_sale:
            cursor.close(); db.close(); return redirect(url_for('sales.sales'))
        customer_name = request.form['customer_name']
        amount = float(request.form['amount'])
        sale_date = request.form['sale_date']
        description = request.form.get('description', '')
        cursor.execute("""
            UPDATE sales SET customer_name=%s, amount=%s, sale_date=%s, description=%s
            WHERE id=%s AND user_id=%s AND deleted_at IS NULL
        """, (customer_name, amount, sale_date, description, sale_id, session['user_id']))
        db.commit()
        cursor.execute("SELECT * FROM sales WHERE id = %s", (sale_id,))
        new_sale = cursor.fetchone()
        log_audit(session['user_id'], session['username'], 'UPDATE', 'sales', sale_id, old_values=old_sale, new_values=new_sale)
        cursor.close(); db.close()
        return redirect(url_for('sales.sales'))
    cursor.execute("SELECT * FROM sales WHERE id = %s AND user_id = %s AND deleted_at IS NULL", (sale_id, session['user_id']))
    sale = cursor.fetchone()
    if not sale:
        cursor.close(); db.close(); return redirect(url_for('sales.sales'))
    cursor.close(); db.close()
    return render_template('edit_sale.html', username=session['username'], sale=sale, today=date.today().isoformat())

@sales_bp.route('/receipt/<int:sale_id>')
def receipt(sale_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    cursor.execute("""
        SELECT s.*, u.username, u.business_name FROM sales s
        JOIN users u ON s.user_id = u.id WHERE s.id = %s AND u.business_id = %s AND s.deleted_at IS NULL
    """, (sale_id, business_id))
    sale = cursor.fetchone()
    if not sale:
        cursor.close(); db.close(); flash('Sale not found', 'error'); return redirect(url_for('sales.sales'))
    
    # Get sale items
    cursor.execute("SELECT * FROM sale_items WHERE sale_id = %s", (sale_id,))
    items = cursor.fetchall()
    
    cursor.execute("""
        SELECT username, business_name, business_id, vat_registered FROM users
        WHERE business_id = %s AND role IN ('admin', 'owner') LIMIT 1
    """, (business_id,))
    owner = cursor.fetchone()
    cursor.close(); db.close()
    
    business_name = owner['business_name'] if owner and owner.get('business_name') else session.get('business_name', 'My Business')
    business_id_num = owner['business_id'] if owner and owner.get('business_id') else business_id
    vat_registered = bool(owner['vat_registered']) if owner else False
    
    return render_template('receipt.html', sale=sale, items=items, amount=float(sale['amount']),
                         business_name=business_name, business_id=business_id_num,
                         receipt_number=f"TARA-{sale_id:06d}", receipt_title='Sales Receipt',
                         receipt_date=str(sale['sale_date']), customer_label='Bill To',
                         customer_name=sale['customer_name'],
                         description=sale.get('description', 'Sale of goods/services'),
                         today=date.today(), back_url='sales', username=session['username'],
                         vat_registered=vat_registered)

@sales_bp.route('/convert_sale_to_invoice/<int:sale_id>')
def convert_sale_to_invoice(sale_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    if session.get('plan') not in ['professional', 'suite']:
        flash('AR requires Pro or Enterprise plan.', 'error'); return redirect(url_for('sales.sales'))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM sales WHERE id = %s AND user_id = %s", (sale_id, session['user_id']))
    sale = cursor.fetchone()
    if not sale:
        cursor.close(); db.close(); flash('Sale not found.', 'error'); return redirect(url_for('sales.sales'))
    cursor.execute("SELECT id FROM customers WHERE name = %s AND user_id = %s", (sale['customer_name'], session['user_id']))
    customer = cursor.fetchone()
    if not customer:
        cursor.execute("INSERT INTO customers (user_id, name) VALUES (%s,%s)", (session['user_id'], sale['customer_name']))
        customer_id = cursor.lastrowid
    else:
        customer_id = customer['id']
    invoice_number = f"INV-{date.today().strftime('%Y%m%d')}-{sale_id}"
    cursor.execute("""
        INSERT INTO invoices (user_id, customer_id, invoice_number, amount, description, due_date, status)
        VALUES (%s,%s,%s,%s,%s,%s,'unpaid')
    """, (session['user_id'], customer_id, invoice_number, sale['amount'],
          sale['description'] or f"Sale to {sale['customer_name']}", date.today()))
    db.commit()
    cursor.close(); db.close()
    flash(f'Invoice #{invoice_number} created!', 'success')
    return redirect(url_for('ar.ar'))

@sales_bp.route('/receipt/payment/<int:payment_id>')
def receipt_payment(payment_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    cursor.execute("""
        SELECT p.*, COALESCE(i.invoice_number, CONCAT('Cash-', t.id)) as doc_number,
            COALESCE(c.name, t.description) as from_name,
            CASE WHEN p.invoice_id IS NOT NULL THEN 'AR Payment' ELSE 'Cash Income' END as receipt_type
        FROM payments p LEFT JOIN invoices i ON p.invoice_id = i.id
        LEFT JOIN customers c ON i.customer_id = c.id
        LEFT JOIN transactions t ON t.description LIKE CONCAT('%%', p.reference_number, '%%') AND t.user_id = p.user_id
        WHERE p.id = %s AND p.user_id = %s ORDER BY t.id DESC LIMIT 1
    """, (payment_id, session['user_id']))
    payment = cursor.fetchone()
    if not payment:
        cursor.close(); db.close(); flash('Payment not found', 'error'); return redirect(url_for('sales.sales'))
    cursor.execute("""
        SELECT username, business_name, business_id, vat_registered FROM users
        WHERE business_id = %s AND role IN ('admin', 'owner') LIMIT 1
    """, (business_id,))
    owner = cursor.fetchone()
    cursor.close(); db.close()
    business_name = owner['business_name'] if owner and owner.get('business_name') else 'My Business'
    business_id_num = owner['business_id'] if owner and owner.get('business_id') else business_id
    vat_registered = bool(owner['vat_registered']) if owner else False
    method_display = payment['payment_method'].replace('_', ' ').title() if payment.get('payment_method') else 'Cash'
    back_url = 'ar' if payment.get('invoice_id') else 'cash'
    return render_template('receipt.html', receipt_number=f"RCPT-{payment_id:06d}",
                         receipt_title='Payment Receipt', receipt_date=str(payment['payment_date']),
                         business_name=business_name, business_id=business_id_num,
                         customer_label='Received From', customer_name=payment['from_name'] or 'Customer',
                         description=payment['notes'] or 'Payment received', amount=float(payment['amount']),
                         payment_method=method_display, reference_number=payment['reference_number'] or '',
                         invoice_number=payment['doc_number'] if payment.get('invoice_id') else '',
                         today=date.today(), back_url=back_url, username=session['username'],
                         vat_registered=vat_registered)