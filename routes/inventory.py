from flask import Blueprint, render_template, request, session, redirect, url_for
from models.database import get_db
from models.audit import log_audit

inventory_bp = Blueprint('inventory', __name__)

@inventory_bp.route('/inventory')
def inventory():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get all products (excluding soft-deleted)
    cursor.execute("""
        SELECT p.* FROM products p
        JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s AND p.deleted_at IS NULL
        ORDER BY p.name
    """, (session['business_id'],))
    products = cursor.fetchall()
    
    # Calculate total stock value (excluding soft-deleted)
    total_value = sum(p['quantity'] * p['price'] for p in products)
    
    # Get low stock products (quantity < reorder_level)
    low_stock = [p for p in products if p['quantity'] < p['reorder_level']]
    
    cursor.close()
    db.close()
    
    return render_template('inventory.html',
                         username=session['username'],
                         products=products,
                         total_value=total_value,
                         low_stock=low_stock)

@inventory_bp.route('/add_product', methods=['POST'])
def add_product():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    name = request.form['name']
    price = float(request.form['price'])
    quantity = int(request.form.get('quantity', 0))
    category = request.form.get('category', '')
    description = request.form.get('description', '')
    reorder_level = int(request.form.get('reorder_level', 5))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO products (user_id, name, description, quantity, price, category, reorder_level)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (session['user_id'], name, description, quantity, price, category, reorder_level))
    db.commit()
    cursor.close()
    db.close()
    
    return redirect(url_for('inventory.inventory'))

@inventory_bp.route('/adjust_stock/<int:product_id>', methods=['POST'])
def adjust_stock(product_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    quantity = int(request.form['quantity'])
    action = request.form['action']
    
    db = get_db()
    cursor = db.cursor()
    
    if action == 'add':
        cursor.execute("UPDATE products SET quantity = quantity + %s WHERE id = %s AND user_id = %s", 
                      (quantity, product_id, session['user_id']))
    elif action == 'remove':
        cursor.execute("UPDATE products SET quantity = quantity - %s WHERE id = %s AND user_id = %s AND quantity >= %s", 
                      (quantity, product_id, session['user_id'], quantity))
    
    db.commit()
    cursor.close()
    db.close()
    
    return redirect(url_for('inventory.inventory'))

@inventory_bp.route('/delete_product/<int:product_id>')
def delete_product(product_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM products WHERE id = %s AND user_id = %s", 
                   (product_id, session['user_id']))
    product = cursor.fetchone()
    
    if product and product.get('deleted_at') is None:
        cursor.execute("""
            UPDATE products SET deleted_at = NOW() 
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (product_id, session['user_id']))
        db.commit()
    
    cursor.close()
    db.close()
    
    return redirect(url_for('inventory.inventory'))

@inventory_bp.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if request.method == 'POST':
        cursor.execute("SELECT * FROM products WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                       (product_id, session['user_id']))
        old_product = cursor.fetchone()
        
        if not old_product:
            cursor.close()
            db.close()
            return redirect(url_for('inventory.inventory'))
        
        name = request.form['name']
        price = float(request.form['price'])
        quantity = int(request.form.get('quantity', 0))
        category = request.form.get('category', '')
        description = request.form.get('description', '')
        reorder_level = int(request.form.get('reorder_level', 5))
        
        cursor.execute("""
            UPDATE products 
            SET name = %s, price = %s, quantity = %s, category = %s, 
                description = %s, reorder_level = %s
            WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """, (name, price, quantity, category, description, reorder_level, 
              product_id, session['user_id']))
        db.commit()
        
        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        new_product = cursor.fetchone()
        
        cursor.close()
        db.close()
        return redirect(url_for('inventory.inventory'))
    
    cursor.execute("SELECT * FROM products WHERE id = %s AND user_id = %s AND deleted_at IS NULL", 
                   (product_id, session['user_id']))
    product = cursor.fetchone()
    
    if not product:
        cursor.close()
        db.close()
        return redirect(url_for('inventory.inventory'))
    
    cursor.close()
    db.close()
    
    return render_template('edit_product.html',
                         username=session['username'],
                         product=product)