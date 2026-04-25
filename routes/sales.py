from flask import Blueprint, render_template, request, session, redirect, url_for
from datetime import date
from models.database import get_db
from models.audit import log_audit

sales_bp = Blueprint('sales', __name__)

@sales_bp.route('/sales')
def sales():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get all sales (excluding soft-deleted)
    cursor.execute("""
        SELECT * FROM sales 
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY sale_date DESC
    """, (session['user_id'],))
    sales_list = cursor.fetchall()
    
    # Get total sales (all time, excluding soft-deleted)
    cursor.execute("""
        SELECT SUM(amount) as total FROM sales 
        WHERE user_id = %s AND deleted_at IS NULL
    """, (session['user_id'],))
    total_result = cursor.fetchone()
    total_sales = float(total_result['total']) if total_result['total'] is not None else 0.0
    
    # Get this month's sales (excluding soft-deleted)
    today = date.today()
    first_day = today.replace(day=1)
    
    cursor.execute("""
        SELECT SUM(amount) as total FROM sales 
        WHERE user_id = %s AND deleted_at IS NULL
        AND sale_date BETWEEN %s AND %s
    """, (session['user_id'], first_day, today))
    monthly_result = cursor.fetchone()
    monthly_sales = float(monthly_result['total']) if monthly_result['total'] is not None else 0.0
    
    # Get products for dropdown (excluding soft-deleted)
    cursor.execute("""
        SELECT id, name, price, quantity FROM products 
        WHERE user_id = %s AND deleted_at IS NULL
    """, (session['user_id'],))
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
        product_id = int(product_id)
        quantity = int(request.form.get('quantity', 1))
        
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        cursor.execute("SELECT name, price FROM products WHERE id = %s AND user_id = %s", 
                       (product_id, session['user_id']))
        product = cursor.fetchone()
        
        if product:
            amount = product['price'] * quantity
            customer_name = request.form.get('customer_name', 'Walk-in Customer')
            description = f"{quantity}x {product['name']}"
            sale_date = request.form.get('sale_date', date.today())
            
            cursor.execute("""
                INSERT INTO sales (user_id, customer_name, amount, sale_date, description)
                VALUES (%s, %s, %s, %s, %s)
            """, (session['user_id'], customer_name, amount, sale_date, description))
            
            cursor.execute("""
                UPDATE products SET quantity = quantity - %s 
                WHERE id = %s AND user_id = %s AND quantity >= %s
            """, (quantity, product_id, session['user_id'], quantity))
            
            db.commit()
        cursor.close()
        db.close()
        
    else:
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