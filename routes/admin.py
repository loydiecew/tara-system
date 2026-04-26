from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify
from datetime import datetime
from models.database import get_db
from models.audit import log_audit
import hashlib

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/users')
def admin_users():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT id, username, full_name, role, created_at 
        FROM users 
        WHERE business_id = %s
        ORDER BY created_at ASC
    """, (session.get('business_id'),))
    
    users = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('admin_users.html', users=users, username=session['username'])

@admin_bp.route('/admin/add_user', methods=['POST'])
def admin_add_user():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))
    
    username = request.form['username']
    password = request.form['password']
    full_name = request.form['full_name']
    role = request.form['role']
    
    hashed = hashlib.sha256(password.encode()).hexdigest()
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        # New user gets same business_id, business_password, business_name, plan_id as the admin
        cursor.execute("""
            INSERT INTO users (username, password, role, full_name, created_by, 
                               business_id, business_password, business_name, plan_id)
            SELECT %s, %s, %s, %s, %s, 
                   business_id, business_password, business_name, plan_id
            FROM users WHERE id = %s
        """, (username, hashed, role, full_name, session['user_id'], session['user_id']))
        db.commit()
    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return f"Error: {e}", 400
    
    cursor.close()
    db.close()
    
    return redirect(url_for('admin.admin_users'))

@admin_bp.route('/admin/delete_user/<int:user_id>')
def admin_delete_user(user_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))
    
    if user_id == session['user_id']:
        return "Cannot delete your own account", 400
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    db.commit()
    cursor.close()
    db.close()
    
    return redirect(url_for('admin.admin_users'))

@admin_bp.route('/admin/restore')
def admin_restore():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))
    
    module_filter = request.args.get('filter', 'all')
    search_query = request.args.get('search', '')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id')
    
    deleted_items = []
    
    def add_items(items, module_name, type_code, module_type_display):
        if module_filter == 'all' or module_filter == module_name:
            for item in items:
                item['type_code'] = type_code
                item['module_type'] = module_type_display
                if search_query:
                    if search_query.lower() in str(item.get('description', '')).lower():
                        deleted_items.append(item)
                else:
                    deleted_items.append(item)
    
    if module_filter == 'all' or module_filter == 'transactions':
        cursor.execute("""
            SELECT t.id, t.description, t.amount, t.transaction_date as date
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.deleted_at IS NOT NULL
            ORDER BY t.deleted_at DESC
        """, (business_id,))
        add_items(cursor.fetchall(), 'transactions', 1, '💰 Transaction')
    
    if module_filter == 'all' or module_filter == 'sales':
        cursor.execute("""
            SELECT s.id, s.customer_name as description, s.amount, s.sale_date as date
            FROM sales s
            JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.deleted_at IS NOT NULL
            ORDER BY s.deleted_at DESC
        """, (business_id,))
        add_items(cursor.fetchall(), 'sales', 2, '📈 Sale')
    
    if module_filter == 'all' or module_filter == 'invoices':
        cursor.execute("""
            SELECT i.id, CONCAT(c.name, ' - ₱', i.amount) as description, i.amount, i.due_date as date
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            JOIN users u ON i.user_id = u.id
            WHERE u.business_id = %s AND i.deleted_at IS NOT NULL
            ORDER BY i.deleted_at DESC
        """, (business_id,))
        add_items(cursor.fetchall(), 'invoices', 3, '📄 Invoice')
    
    if module_filter == 'all' or module_filter == 'bills':
        cursor.execute("""
            SELECT b.id, CONCAT(s.name, ' - ₱', b.amount) as description, b.amount, b.due_date as date
            FROM bills b
            JOIN suppliers s ON b.supplier_id = s.id
            JOIN users u ON b.user_id = u.id
            WHERE u.business_id = %s AND b.deleted_at IS NOT NULL
            ORDER BY b.deleted_at DESC
        """, (business_id,))
        add_items(cursor.fetchall(), 'bills', 4, '📃 Bill')
    
    if module_filter == 'all' or module_filter == 'products':
        cursor.execute("""
            SELECT p.id, CONCAT(p.name, ' (', p.quantity, ' in stock)') as description, p.price as amount, p.created_at as date
            FROM products p
            JOIN users u ON p.user_id = u.id
            WHERE u.business_id = %s AND p.deleted_at IS NOT NULL
            ORDER BY p.deleted_at DESC
        """, (business_id,))
        add_items(cursor.fetchall(), 'products', 5, '📦 Product')
    
    cursor.close()
    db.close()
    
    module_counts = {
        'transactions': len([i for i in deleted_items if i.get('module') == 'transaction']),
        'sales': len([i for i in deleted_items if i.get('module') == 'sale']),
        'invoices': len([i for i in deleted_items if i.get('module') == 'invoice']),
        'bills': len([i for i in deleted_items if i.get('module') == 'bill']),
        'products': len([i for i in deleted_items if i.get('module') == 'product'])
    }
    
    return render_template('admin_restore.html',
                         username=session['username'],
                         deleted_items=deleted_items,
                         current_filter=module_filter,
                         search_query=search_query,
                         module_counts=module_counts)

@admin_bp.route('/admin/restore/<int:type_code>/<int:record_id>')
def admin_restore_item(type_code, record_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))
    
    table_map = {1: 'transactions', 2: 'sales', 3: 'invoices', 4: 'bills', 5: 'products'}
    table_name = table_map.get(type_code)
    if not table_name:
        return f"Invalid type code: {type_code}", 400
    
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute(f"UPDATE {table_name} SET deleted_at = NULL WHERE id = %s AND user_id = %s", 
                   (record_id, session['user_id']))
    db.commit()
    log_audit(session['user_id'], session['username'], 'RESTORE', table_name, 
              record_id, new_values={'restored_at': str(datetime.now())})
    cursor.close()
    db.close()
    
    return redirect(url_for('admin.admin_restore'))

@admin_bp.route('/admin/audit')
def admin_audit():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('auth.login'))
    
    action_filter = request.args.get('action', 'all')
    table_filter = request.args.get('table', 'all')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id')
    
    query = """
        SELECT a.* FROM audit_log a
        JOIN users u ON a.user_id = u.id
        WHERE u.business_id = %s
    """
    params = [business_id]
    
    if action_filter != 'all':
        query += " AND a.action = %s"
        params.append(action_filter)
    if table_filter != 'all':
        query += " AND a.table_name = %s"
        params.append(table_filter)
    query += " ORDER BY a.created_at DESC LIMIT 500"
    
    cursor.execute(query, params)
    logs = cursor.fetchall()
    
    cursor.execute("SELECT DISTINCT action FROM audit_log a JOIN users u ON a.user_id = u.id WHERE u.business_id = %s", (business_id,))
    actions = [row['action'] for row in cursor.fetchall()]
    cursor.execute("SELECT DISTINCT table_name FROM audit_log a JOIN users u ON a.user_id = u.id WHERE u.business_id = %s", (business_id,))
    tables = [row['table_name'] for row in cursor.fetchall()]
    
    cursor.close()
    db.close()
    
    return render_template('admin_audit.html', username=session['username'], logs=logs,
                         actions=actions, tables=tables, current_action=action_filter, current_table=table_filter)

@admin_bp.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    db.close()
    
    if user:
        if 'full_name' not in user or not user['full_name']:
            user['full_name'] = session['username']
        if 'email' not in user:
            user['email'] = ''
        if 'industry' not in user or not user['industry']:
            user['industry'] = 'retail'
        if 'created_at' not in user:
            user['created_at'] = datetime.now()
    
    return render_template('profile.html', username=session['username'], user=user)

@admin_bp.route('/admin/users/api')
def admin_users_api():
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, username, full_name, role, created_at 
        FROM users 
        WHERE business_id = %s
        ORDER BY created_at ASC
    """, (session.get('business_id'),))
    users = cursor.fetchall()
    cursor.close()
    db.close()
    
    for u in users:
        if u.get('created_at'):
            u['created_at'] = u['created_at'].isoformat()
    
    return jsonify(users)

@admin_bp.route('/admin/restore/data')
def admin_restore_data():
    if 'user_id' not in session or session.get('role') != 'admin':
        return jsonify({'error': 'Unauthorized'}), 401
    
    module_filter = request.args.get('filter', 'all')
    business_id = session.get('business_id')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    deleted_items = []
    
    def add_items(items, module_name, type_code, module_type_display):
        if module_filter == 'all' or module_filter == module_name:
            for item in items:
                item['type_code'] = type_code
                item['module_type'] = module_type_display
                deleted_items.append(item)
    
    if module_filter == 'all' or module_filter == 'transactions':
        cursor.execute("""
            SELECT t.id, t.description, t.amount, t.transaction_date as date
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            WHERE u.business_id = %s AND t.deleted_at IS NOT NULL
            ORDER BY t.deleted_at DESC
        """, (business_id,))
        add_items(cursor.fetchall(), 'transactions', 1, '💰 Transaction')
    
    if module_filter == 'all' or module_filter == 'sales':
        cursor.execute("""
            SELECT s.id, s.customer_name as description, s.amount, s.sale_date as date
            FROM sales s
            JOIN users u ON s.user_id = u.id
            WHERE u.business_id = %s AND s.deleted_at IS NOT NULL
            ORDER BY s.deleted_at DESC
        """, (business_id,))
        add_items(cursor.fetchall(), 'sales', 2, '📈 Sale')
    
    if module_filter == 'all' or module_filter == 'invoices':
        cursor.execute("""
            SELECT i.id, CONCAT(c.name, ' - ₱', i.amount) as description, i.amount, i.due_date as date
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            JOIN users u ON i.user_id = u.id
            WHERE u.business_id = %s AND i.deleted_at IS NOT NULL
            ORDER BY i.deleted_at DESC
        """, (business_id,))
        add_items(cursor.fetchall(), 'invoices', 3, '📄 Invoice')
    
    if module_filter == 'all' or module_filter == 'bills':
        cursor.execute("""
            SELECT b.id, CONCAT(s.name, ' - ₱', b.amount) as description, b.amount, b.due_date as date
            FROM bills b
            JOIN suppliers s ON b.supplier_id = s.id
            JOIN users u ON b.user_id = u.id
            WHERE u.business_id = %s AND b.deleted_at IS NOT NULL
            ORDER BY b.deleted_at DESC
        """, (business_id,))
        add_items(cursor.fetchall(), 'bills', 4, '📃 Bill')
    
    if module_filter == 'all' or module_filter == 'products':
        cursor.execute("""
            SELECT p.id, CONCAT(p.name, ' (', p.quantity, ' in stock)') as description, p.price as amount, p.created_at as date
            FROM products p
            JOIN users u ON p.user_id = u.id
            WHERE u.business_id = %s AND p.deleted_at IS NOT NULL
            ORDER BY p.deleted_at DESC
        """, (business_id,))
        add_items(cursor.fetchall(), 'products', 5, '📦 Product')
    
    cursor.close()
    db.close()
    
    return jsonify({'items': deleted_items, 'current_filter': module_filter})
