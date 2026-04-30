from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date
from models.database import get_db
from models.audit import log_audit

sales_bp = Blueprint('sales', __name__)

# Helper function to create journal entry (import from cash or define here)
def create_journal_entry(user_id, entry_date, description, lines):
    """Create a journal entry with debit/credit lines"""
    from models.database import get_db
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        INSERT INTO journal_entries (user_id, entry_date, description)
        VALUES (%s, %s, %s)
    """, (user_id, entry_date, description))
    entry_id = cursor.lastrowid
    
    for line in lines:
        cursor.execute("""
            INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
            VALUES (%s, %s, %s, %s)
        """, (entry_id, line['account_id'], line.get('debit', 0), line.get('credit', 0)))
    
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
    
    # Get all sales for this business (excluding soft-deleted)
    cursor.execute("""
        SELECT s.* FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.deleted_at IS NULL
        ORDER BY s.sale_date DESC
    """, (business_id,))
    sales_list = cursor.fetchall()
    
    # Get total sales (all time) for this business
    cursor.execute("""
        SELECT SUM(s.amount) as total FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.deleted_at IS NULL
    """, (business_id,))
    total_result = cursor.fetchone()
    total_sales = float(total_result['total']) if total_result['total'] is not None else 0.0
    
    # Get this month's sales for this business
    today = date.today()
    first_day = today.replace(day=1)
    
    cursor.execute("""
        SELECT SUM(s.amount) as total FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE u.business_id = %s AND s.deleted_at IS NULL
        AND s.sale_date BETWEEN %s AND %s
    """, (business_id, first_day, today))
    monthly_result = cursor.fetchone()
    monthly_sales = float(monthly_result['total']) if monthly_result['total'] is not None else 0.0
    
    # Get products for dropdown for this business (excluding soft-deleted)
    cursor.execute("""
        SELECT p.id, p.name, p.price, p.quantity FROM products p
        JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.deleted_at IS NULL
    """, (business_id,))
    products = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('sales.html',
                         username=session['username'],
                         sales=sales_list,
                         total_sales=total_sales,
                         monthly_sales=monthly_sales,
                         products=products,
                         today=today.isoformat())

@sales_bp.route('/add_sale', methods=['POST'])
def add_sale():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    product_id = request.form.get('product_id')
    
    if product_id and product_id != '':
        # Sale from inventory dropdown
        product_id = int(product_id)
        quantity = int(request.form.get('quantity', 1))
        
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        # Verify product belongs to user's business
        cursor.execute("""
            SELECT p.name, p.price FROM products p
            JOIN users u ON p.user_id = u.id
            WHERE p.id = %s AND u.business_id = %s
        """, (product_id, session.get('business_id', session['user_id'])))
        product = cursor.fetchone()
        
        if product:
            amount = product['price'] * quantity
            customer_name = request.form.get('customer_name', 'Walk-in Customer')
            description = f"{quantity}x {product['name']}"
            sale_date = request.form.get('sale_date', date.today())
            
            # Insert sale
            cursor.execute("""
                INSERT INTO sales (user_id, customer_name, amount, sale_date, description)
                VALUES (%s, %s, %s, %s, %s)
            """, (session['user_id'], customer_name, amount, sale_date, description))
            
            # Deduct from inventory
            cursor.execute("""
                UPDATE products SET quantity = quantity - %s 
                WHERE id = %s AND user_id = %s AND quantity >= %s
            """, (quantity, product_id, session['user_id'], quantity))
            
            db.commit()
            
            # Create journal entry for Pro users
            if session.get('plan') in ['pro', 'enterprise']:
                cursor2 = db.cursor(dictionary=True)
                
                # Get account IDs
                cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '1000'")  # Cash
                cash_account = cursor2.fetchone()
                cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '4000'")  # Sales Revenue
                revenue_account = cursor2.fetchone()
                
                if cash_account and revenue_account:
                    lines = [
                        {'account_id': cash_account['id'], 'debit': amount, 'credit': 0},
                        {'account_id': revenue_account['id'], 'debit': 0, 'credit': amount}
                    ]
                    create_journal_entry(
                        user_id=session['user_id'],
                        entry_date=sale_date,
                        description=f"Sale to {customer_name} - {description}",
                        lines=lines
                    )
                
                cursor2.close()
            
            flash(f'Sale recorded successfully!', 'success')
            
        cursor.close()
        db.close()
        
    else:
        # Manual sale
        customer_name = request.form.get('customer_name_manual', request.form.get('customer_name', 'Walk-in Customer'))
        amount = float(request.form.get('amount_manual', request.form.get('amount', 0)))
        sale_date = request.form.get('sale_date', date.today())
        description = request.form.get('description_manual', request.form.get('description', ''))
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO sales (user_id, customer_name, amount, sale_date, description)
            VALUES (%s, %s, %s, %s, %s)
        """, (session['user_id'], customer_name, amount, sale_date, description))
        db.commit()
        
        # Create journal entry for Pro users
        if session.get('plan') in ['pro', 'enterprise']:
            cursor2 = db.cursor(dictionary=True)
            
            # Get account IDs
            cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '1000'")  # Cash
            cash_account = cursor2.fetchone()
            cursor2.execute("SELECT id FROM chart_of_accounts WHERE code = '4000'")  # Sales Revenue
            revenue_account = cursor2.fetchone()
            
            if cash_account and revenue_account:
                lines = [
                    {'account_id': cash_account['id'], 'debit': amount, 'credit': 0},
                    {'account_id': revenue_account['id'], 'debit': 0, 'credit': amount}
                ]
                create_journal_entry(
                    user_id=session['user_id'],
                    entry_date=sale_date,
                    description=f"Sale to {customer_name} - {description or 'Manual sale'}",
                    lines=lines
                )
            
            cursor2.close()
        
        flash(f'Sale recorded successfully!', 'success')
        cursor.close()
        db.close()
    
    return redirect(url_for('sales.sales'))

@sales_bp.route('/delete_sale/<int:sale_id>')
def delete_sale(sale_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM sales WHERE id = %s AND user_id = %s", 
                   (sale_id, session['user_id']))
    sale = cursor.fetchone()
    
    if sale and sale.get('deleted_at') is None:
        cursor.execute("""
            UPDATE sales SET deleted_at = NOW() 
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (sale_id, session['user_id']))
        db.commit()
        
        log_audit(session['user_id'], session['username'], 'DELETE', 'sales', 
                  sale_id, old_values=sale)
    
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
        cursor.execute("SELECT * FROM sales WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                       (sale_id, session['user_id']))
        old_sale = cursor.fetchone()
        
        if not old_sale:
            cursor.close()
            db.close()
            return redirect(url_for('sales.sales'))
        
        customer_name = request.form['customer_name']
        amount = float(request.form['amount'])
        sale_date = request.form['sale_date']
        description = request.form.get('description', '')
        
        cursor.execute("""
            UPDATE sales 
            SET customer_name = %s, amount = %s, sale_date = %s, description = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (customer_name, amount, sale_date, description, sale_id, session['user_id']))
        db.commit()
        
        cursor.execute("SELECT * FROM sales WHERE id = %s", (sale_id,))
        new_sale = cursor.fetchone()
        
        log_audit(session['user_id'], session['username'], 'UPDATE', 'sales', 
                  sale_id, old_values=old_sale, new_values=new_sale)
        
        cursor.close()
        db.close()
        return redirect(url_for('sales.sales'))
    
    cursor.execute("SELECT * FROM sales WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                   (sale_id, session['user_id']))
    sale = cursor.fetchone()
    
    if not sale:
        cursor.close()
        db.close()
        return redirect(url_for('sales.sales'))
    
    cursor.close()
    db.close()
    
    today = date.today().isoformat()
    
    return render_template('edit_sale.html',
                         username=session['username'],
                         sale=sale,
                         today=today)

@sales_bp.route('/receipt/<int:sale_id>')
def receipt(sale_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    business_id = session.get('business_id', session['user_id'])
    
    # Get the sale
    cursor.execute("""
        SELECT s.*, u.username, u.business_name
        FROM sales s
        JOIN users u ON s.user_id = u.id
        WHERE s.id = %s AND u.business_id = %s AND s.deleted_at IS NULL
    """, (sale_id, business_id))
    sale = cursor.fetchone()
    
    if not sale:
        cursor.close()
        db.close()
        flash('Sale not found', 'error')
        return redirect(url_for('sales.sales'))
    
    # Get business owner details
    cursor.execute("""
        SELECT username, business_name, business_id FROM users
        WHERE business_id = %s AND role IN ('admin', 'owner')
        LIMIT 1
    """, (business_id,))
    owner = cursor.fetchone()
    
    cursor.close()
    db.close()
    
    business_name = owner['business_name'] if owner and owner.get('business_name') else session.get('business_name', 'My Business')
    business_id_num = owner['business_id'] if owner and owner.get('business_id') else business_id
    
    receipt_number = f"TARA-{sale_id:06d}"
    today = date.today()
    
    return render_template('receipt.html',
                         sale=sale,
                         business_name=business_name,
                         business_id=business_id_num,
                         receipt_number=receipt_number,
                         today=today,
                         username=session['username'])