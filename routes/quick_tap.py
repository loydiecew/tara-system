from models.audit import log_audit
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from models.database import get_db
from datetime import date, datetime, timedelta
import json
import csv
import io

quick_tap_bp = Blueprint('quick_tap', __name__)

# ────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────

def get_streak(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT DISTINCT sale_date FROM sales 
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY sale_date DESC LIMIT 60
    """, (user_id,))
    dates = [row[0] for row in cursor.fetchall()]
    cursor.close()
    db.close()

    if not dates or dates[0] != date.today():
        return 0

    streak = 1
    today = date.today()
    for i in range(1, len(dates)):
        if dates[i] == today - timedelta(days=i):
            streak += 1
        else:
            break
    return streak


def get_yesterday_comparison(user_id):
    db = get_db()
    cursor = db.cursor()
    today = date.today()
    yesterday = today - timedelta(days=1)

    cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM sales WHERE user_id = %s AND sale_date = %s AND deleted_at IS NULL", (user_id, today))
    today_total = float(cursor.fetchone()[0])

    cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM sales WHERE user_id = %s AND sale_date = %s AND deleted_at IS NULL", (user_id, yesterday))
    yesterday_total = float(cursor.fetchone()[0])
    cursor.close()
    db.close()

    pct_change = ((today_total - yesterday_total) / yesterday_total * 100) if yesterday_total > 0 else (100 if today_total > 0 else 0)

    return {
        'today': today_total,
        'yesterday': yesterday_total,
        'pct_change': round(pct_change, 1),
        'is_up': today_total >= yesterday_total
    }


def get_today_summary(user_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    today = date.today()

    cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM sales WHERE user_id = %s AND sale_date = %s AND deleted_at IS NULL", (user_id, today))
    sales_total = float(cursor.fetchone()['total'])

    cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE user_id = %s AND transaction_date = %s AND type = 'expense' AND deleted_at IS NULL", (user_id, today))
    expense_total = float(cursor.fetchone()['total'])

    cursor.execute("""
        SELECT COALESCE(SUM(i.amount), 0) - COALESCE(SUM(p.amount), 0) as outstanding
        FROM invoices i
        LEFT JOIN payments p ON i.id = p.invoice_id
        WHERE i.user_id = %s AND i.status IN ('unpaid', 'overdue') AND i.deleted_at IS NULL
    """, (user_id,))
    credit_outstanding = float(cursor.fetchone()['outstanding'])
    cursor.close()
    db.close()

    return {
        'sales_total': sales_total,
        'expense_total': expense_total,
        'profit': sales_total - expense_total,
        'credit_outstanding': credit_outstanding
    }


def get_best_day(user_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT sale_date, SUM(amount) as total FROM sales
        WHERE user_id = %s AND sale_date >= %s AND deleted_at IS NULL
        GROUP BY sale_date ORDER BY total DESC LIMIT 1
    """, (user_id, date.today().replace(day=1)))
    result = cursor.fetchone()
    cursor.close()
    db.close()
    return result


def get_weekly_summary(user_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    last_monday = monday - timedelta(days=7)
    last_sunday = monday - timedelta(days=1)

    cursor.execute("SELECT COALESCE(SUM(amount), 0) as total_sales, COUNT(*) as txns FROM sales WHERE user_id = %s AND sale_date >= %s AND sale_date <= %s AND deleted_at IS NULL", (user_id, monday, today))
    sales = cursor.fetchone()

    cursor.execute("SELECT COALESCE(SUM(amount), 0) as total_expenses FROM transactions WHERE user_id = %s AND transaction_date >= %s AND transaction_date <= %s AND type = 'expense' AND deleted_at IS NULL", (user_id, monday, today))
    expenses = cursor.fetchone()

    cursor.execute("SELECT COALESCE(SUM(amount), 0) as total_sales FROM sales WHERE user_id = %s AND sale_date >= %s AND sale_date <= %s AND deleted_at IS NULL", (user_id, last_monday, last_sunday))
    last_week_sales = float(cursor.fetchone()['total_sales'])

    cursor.execute("""
        SELECT si.product_name, SUM(si.amount) as total
        FROM sale_items si JOIN sales s ON si.sale_id = s.id
        WHERE s.user_id = %s AND s.sale_date >= %s AND s.sale_date <= %s AND s.deleted_at IS NULL
        GROUP BY si.product_name ORDER BY total DESC LIMIT 1
    """, (user_id, monday, today))
    best_product = cursor.fetchone()

    cursor.execute("SELECT sale_date, SUM(amount) as total FROM sales WHERE user_id = %s AND sale_date >= %s AND sale_date <= %s AND deleted_at IS NULL GROUP BY sale_date ORDER BY total DESC LIMIT 1", (user_id, monday, today))
    best_day = cursor.fetchone()

    cursor.close()
    db.close()

    return {
        'total_sales': float(sales['total_sales']),
        'total_expenses': float(expenses['total_expenses']),
        'profit': float(sales['total_sales']) - float(expenses['total_expenses']),
        'transaction_count': sales['txns'],
        'last_week_sales': last_week_sales,
        'best_product': best_product['product_name'] if best_product else None,
        'best_product_amount': float(best_product['total']) if best_product else 0,
        'best_day': best_day,
        'week_start': monday,
        'week_end': today
    }


def get_heatmap_data(user_id):
    db = get_db()
    cursor = db.cursor()
    heatmap_start = date.today() - timedelta(days=182)

    cursor.execute("SELECT sale_date, COALESCE(SUM(amount), 0) as total FROM sales WHERE user_id = %s AND sale_date >= %s AND deleted_at IS NULL GROUP BY sale_date ORDER BY sale_date ASC", (user_id, heatmap_start))
    daily_sales = cursor.fetchall()

    cursor.execute("SELECT transaction_date, COALESCE(SUM(amount), 0) as total FROM transactions WHERE user_id = %s AND type = 'income' AND transaction_date >= %s AND deleted_at IS NULL GROUP BY transaction_date ORDER BY transaction_date ASC", (user_id, heatmap_start))
    daily_income = cursor.fetchall()

    heatmap_dict = {}
    for d in daily_sales:
        key = d[0].isoformat() if hasattr(d[0], 'isoformat') else str(d[0])
        heatmap_dict[key] = float(d[1] or 0)
    for d in daily_income:
        key = d[0].isoformat() if hasattr(d[0], 'isoformat') else str(d[0])
        heatmap_dict[key] = heatmap_dict.get(key, 0) + float(d[1] or 0)

    cursor.close()
    db.close()
    return json.dumps([{'date': k, 'amount': v} for k, v in heatmap_dict.items()])


def get_recent_activity(user_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    today = date.today()

    cursor.execute("""
        (SELECT 'sale' as type, s.description as name, s.amount, s.created_at as ts
         FROM sales s WHERE s.user_id = %s AND s.sale_date = %s AND s.deleted_at IS NULL)
        UNION ALL
        (SELECT 'expense' as type, t.description as name, t.amount, t.created_at as ts
         FROM transactions t WHERE t.user_id = %s AND t.transaction_date = %s AND t.type = 'expense' AND t.deleted_at IS NULL)
        UNION ALL
        (SELECT 'credit' as type, CONCAT(c.name, ' — ', COALESCE(i.description, 'Credit')) as name, i.amount, i.created_at as ts
         FROM invoices i JOIN customers c ON i.customer_id = c.id
         WHERE i.user_id = %s AND DATE(i.created_at) = %s AND i.deleted_at IS NULL)
        UNION ALL
        (SELECT 'note' as type, t.description as name, 0 as amount, t.created_at as ts
         FROM transactions t WHERE t.user_id = %s AND t.transaction_date = %s AND t.type = 'note' AND t.deleted_at IS NULL)
        ORDER BY ts DESC LIMIT 30
    """, (user_id, today, user_id, today, user_id, today, user_id, today))
    activity = cursor.fetchall()
    cursor.close()
    db.close()
    return activity

def is_first_login(user_id):
    """Check if user has completed onboarding."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM products WHERE user_id = %s AND deleted_at IS NULL", (user_id,))
    product_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) as count FROM sales WHERE user_id = %s AND deleted_at IS NULL", (user_id,))
    sale_count = cursor.fetchone()[0]
    cursor.close()
    db.close()
    return product_count == 0 and sale_count == 0
# ────────────────────────────────────────────────────────────
# ROUTES — QUICK TAP (MAIN)
# ────────────────────────────────────────────────────────────
@quick_tap_bp.route('/quick-tap')
def index():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user_id = session['user_id']

    if is_first_login(user_id) and not request.args.get('skip_onboarding'):
        return render_template('quick_tap_onboarding.html')

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, name, price, quantity, category 
        FROM products 
        WHERE user_id = %s AND deleted_at IS NULL 
        ORDER BY category, name
    """, (user_id,))
    products = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('quick_tap.html',
                           products=products,
                           streak=get_streak(user_id),
                           comparison=get_yesterday_comparison(user_id),
                           summary=get_today_summary(user_id),
                           best_day=get_best_day(user_id),
                           activity=get_recent_activity(user_id),
                           heatmap_data=get_heatmap_data(user_id),
                           today=date.today())

@quick_tap_bp.route('/quick-tap/record', methods=['POST'])
def record_sale():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    user_id = session['user_id']
    data = request.get_json()
    product_id = data.get('product_id')
    product_name = data.get('product_name', 'Quick Sale')
    amount = float(data.get('amount', 0))
    quantity = int(data.get('quantity', 1))

    if amount <= 0:
        return jsonify({'success': False, 'error': 'Amount must be greater than zero'}), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)
    today = date.today()

    try:
        desc = f"{product_name}" + (f" x{quantity}" if quantity > 1 else "")

        cursor.execute("INSERT INTO sales (user_id, customer_name, amount, sale_date, description, payment_method, branch_id) VALUES (%s, 'Walk-in', %s, %s, %s, 'cash', %s)",
                       (user_id, amount, today, desc, session.get('branch_id')))
        sale_id = cursor.lastrowid

        cursor.execute("INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, amount) VALUES (%s, %s, %s, %s, %s, %s)",
                       (sale_id, product_id, product_name, quantity, amount / quantity, amount))

        cursor.execute("INSERT INTO transactions (user_id, amount, type, description, category, transaction_date, payment_method, branch_id) VALUES (%s, %s, 'income', %s, 'Sales', %s, 'cash', %s)",
                       (user_id, amount, desc, today, session.get('branch_id')))

        cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description, reference) VALUES (%s, %s, %s, %s)",
                       (user_id, today, f"Quick Tap: {product_name}", f"QT-{sale_id}"))
        journal_id = cursor.lastrowid

        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 1, %s, 0)", (journal_id, amount))
        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 6, 0, %s)", (journal_id, amount))

        if product_id:
            cursor.execute("SELECT quantity, cogs FROM products WHERE id = %s AND user_id = %s", (product_id, user_id))
            product = cursor.fetchone()
            if product and product['quantity'] is not None and product['quantity'] >= quantity:
                cursor.execute("UPDATE products SET quantity = quantity - %s WHERE id = %s", (quantity, product_id))
                if product['cogs'] and float(product['cogs']) > 0:
                    cogs_total = float(product['cogs']) * quantity
                    cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description, reference) VALUES (%s, %s, %s, %s)",
                                   (user_id, today, f"COGS: {product_name}", f"QT-COGS-{sale_id}"))
                    cogs_jid = cursor.lastrowid
                    cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 8, %s, 0)", (cogs_jid, cogs_total))
                    cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 3, 0, %s)", (cogs_jid, cogs_total))

        db.commit()
        log_audit(user_id, session.get('username', ''), 'CREATE', 'sales', 
                sale_id, new_values={'product': product_name, 'amount': amount, 'date': str(today)})
        cursor.close()
        db.close()

        return jsonify({
            'success': True,
            'message': f'{product_name} — {amount:,.0f}',
            'streak': get_streak(user_id),
            'comparison': get_yesterday_comparison(user_id),
            'summary': get_today_summary(user_id)
        })

    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500


@quick_tap_bp.route('/quick-tap/expense', methods=['POST'])
def record_expense():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    user_id = session['user_id']
    data = request.get_json()
    amount = float(data.get('amount', 0))
    description = data.get('description', 'Expense')
    category = data.get('category', 'General')

    if amount <= 0:
        return jsonify({'success': False, 'error': 'Amount must be greater than zero'}), 400

    db = get_db()
    cursor = db.cursor()
    today = date.today()

    try:
        cursor.execute("INSERT INTO transactions (user_id, amount, type, description, category, transaction_date, branch_id) VALUES (%s, %s, 'expense', %s, %s, %s, %s)",
                       (user_id, amount, description, category, today, session.get('branch_id')))

        cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description, reference) VALUES (%s, %s, %s, %s)",
                       (user_id, today, f"Expense: {description}", f"EXP-{cursor.lastrowid}"))
        journal_id = cursor.lastrowid

        expense_account_map = {'Rent': 9, 'Utilities': 10, 'Supplies': 11, 'Salary': 12, 'General': 11}
        account_id = expense_account_map.get(category, 11)

        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, %s, %s, 0)", (journal_id, account_id, amount))
        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 1, 0, %s)", (journal_id, amount))

        db.commit()
        log_audit(user_id, session.get('username', ''), 'CREATE', 'transactions', 
                cursor.lastrowid, new_values={'description': description, 'amount': amount, 'type': 'expense'})
        cursor.close()
        db.close()

        return jsonify({
            'success': True,
            'message': f'Expense {amount:,.0f} recorded',
            'summary': get_today_summary(user_id)
        })

    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500


@quick_tap_bp.route('/quick-tap/credit', methods=['POST'])
def record_credit():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    user_id = session['user_id']
    data = request.get_json()
    customer_name = data.get('customer_name', '').strip()
    amount = float(data.get('amount', 0))
    item = data.get('item', '').strip()

    if not customer_name:
        return jsonify({'success': False, 'error': 'Enter a name'}), 400
    if amount <= 0:
        return jsonify({'success': False, 'error': 'Enter an amount'}), 400

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute("SELECT id FROM customers WHERE user_id = %s AND name = %s AND deleted_at IS NULL", (user_id, customer_name))
        cust = cursor.fetchone()

        if cust:
            customer_id = cust[0]
        else:
            cursor.execute("INSERT INTO customers (user_id, name) VALUES (%s, %s)", (user_id, customer_name))
            customer_id = cursor.lastrowid

        desc = f"Credit: {item}" if item else "Credit"
        cursor.execute("INSERT INTO invoices (user_id, customer_id, amount, description, status, due_date) VALUES (%s, %s, %s, %s, 'unpaid', DATE_ADD(CURDATE(), INTERVAL 30 DAY))",
                       (user_id, customer_id, amount, desc))

        db.commit()
        log_audit(user_id, session.get('username', ''), 'CREATE', 'invoices', 
                cursor.lastrowid, new_values={'customer': customer_name, 'amount': amount, 'type': 'credit'})
        cursor.close()
        db.close()

        return jsonify({
            'success': True,
            'message': f'{customer_name} — {amount:,.0f}',
            'summary': get_today_summary(user_id)
        })

    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500

@quick_tap_bp.route('/quick-tap/credit/pay', methods=['POST'])
def pay_credit():
    """Record a payment toward credit."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    user_id = session['user_id']
    data = request.get_json()
    invoice_id = data.get('invoice_id')
    amount = float(data.get('amount', 0))

    if not invoice_id or amount <= 0:
        return jsonify({'success': False, 'error': 'Invalid payment'}), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:
        # Join with customers to get the name
        cursor.execute("""
            SELECT i.*, c.name as customer_name
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            WHERE i.id = %s AND i.user_id = %s AND i.deleted_at IS NULL
        """, (invoice_id, user_id))
        invoice = cursor.fetchone()
        
        if not invoice:
            cursor.close()
            db.close()
            return jsonify({'success': False, 'error': 'Not found'}), 404

        # Record payment
        cursor.execute("""
            INSERT INTO payments (user_id, invoice_id, amount, payment_date, payment_method)
            VALUES (%s, %s, %s, CURDATE(), 'cash')
        """, (user_id, invoice_id, amount))

        # Check if fully paid
        cursor.execute("SELECT COALESCE(SUM(amount), 0) as total_paid FROM payments WHERE invoice_id = %s", (invoice_id,))
        paid = float(cursor.fetchone()['total_paid'])

        new_status = 'paid' if paid >= float(invoice['amount']) else 'unpaid'
        cursor.execute("UPDATE invoices SET status = %s WHERE id = %s", (new_status, invoice_id))

        db.commit()
        log_audit(user_id, session.get('username', ''), 'CREATE', 'payments', 
                cursor.lastrowid, new_values={'invoice_id': invoice_id, 'amount': amount})
        customer_name = invoice['customer_name']
        summary = get_today_summary(user_id)
        
        cursor.close()
        db.close()

        return jsonify({
            'success': True,
            'message': f'Received {amount:,.0f} from {customer_name}',
            'summary': summary
        })

    except Exception as e:
        try:
            db.rollback()
        except:
            pass
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500

@quick_tap_bp.route('/quick-tap/reconciliation', methods=['GET', 'POST'])
def reconciliation():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user_id = session['user_id']

    if request.method == 'POST':
        actual_cash = float(request.form.get('actual_cash', 0))
        db = get_db()
        cursor = db.cursor(dictionary=True)
        today = date.today()

        cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM sales WHERE user_id = %s AND sale_date = %s AND deleted_at IS NULL", (user_id, today))
        recorded_sales = float(cursor.fetchone()['total'])

        cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE user_id = %s AND transaction_date = %s AND type = 'expense' AND deleted_at IS NULL", (user_id, today))
        recorded_expenses = float(cursor.fetchone()['total'])

        micro_sales = actual_cash - (recorded_sales - recorded_expenses)

        if micro_sales > 0:
            desc = "Micro Sales (Reconciliation)"
            cursor.execute("INSERT INTO sales (user_id, customer_name, amount, sale_date, description, payment_method, branch_id) VALUES (%s, 'Various', %s, %s, %s, 'cash', %s)",
                           (user_id, micro_sales, today, desc, session.get('branch_id')))
            sid = cursor.lastrowid
            cursor.execute("INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, amount) VALUES (%s, NULL, 'Micro Sales', 1, %s, %s)", (sid, micro_sales, micro_sales))
            cursor.execute("INSERT INTO transactions (user_id, amount, type, description, category, transaction_date, branch_id) VALUES (%s, %s, 'income', %s, 'Sales', %s, %s)",
                           (user_id, micro_sales, desc, today, session.get('branch_id')))
            cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description, reference) VALUES (%s, %s, %s, %s)", (user_id, today, "Micro Sales Reconciliation", f"RECON-{today}"))
            jid = cursor.lastrowid
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 1, %s, 0)", (jid, micro_sales))
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 6, 0, %s)", (jid, micro_sales))

        elif micro_sales < 0:
            shortfall = abs(micro_sales)
            desc = "Cash Shortfall"
            cursor.execute("INSERT INTO transactions (user_id, amount, type, description, category, transaction_date, branch_id) VALUES (%s, %s, 'expense', %s, 'Cash Shortfall', %s, %s)",
                           (user_id, shortfall, desc, today, session.get('branch_id')))
            cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description, reference) VALUES (%s, %s, %s, %s)", (user_id, today, "Cash Shortfall", f"RECON-{today}"))
            jid = cursor.lastrowid
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 11, %s, 0)", (jid, shortfall))
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 1, 0, %s)", (jid, shortfall))

        db.commit()
        log_audit(user_id, session.get('username', ''), 'CREATE', 'reconciliation', 
                0, new_values={'micro_sales': micro_sales, 'date': str(today)})
        cursor.close()
        db.close()
        return redirect(url_for('quick_tap.index'))

    return render_template('reconciliation.html', summary=get_today_summary(user_id), today=date.today())


# ────────────────────────────────────────────────────────────
# ROUTES — PRODUCTS
# ────────────────────────────────────────────────────────────

@quick_tap_bp.route('/quick-tap/products')
def products_page():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, name, price, quantity FROM products WHERE user_id = %s AND deleted_at IS NULL ORDER BY name", (user_id,))
    products = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('quick_tap_products.html', products=products, summary=get_today_summary(user_id))

@quick_tap_bp.route('/quick-tap/products/add', methods=['POST'])
def add_product():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    user_id = session['user_id']
    data = request.get_json()
    name = data.get('name', '').strip()
    price = float(data.get('price', 0))
    category = data.get('category', '').strip() or None
    stock = data.get('stock')

    if not name:
        return jsonify({'success': False, 'error': 'Enter a product name'}), 400
    if price <= 0:
        return jsonify({'success': False, 'error': 'Enter a valid price'}), 400

    quantity = int(stock) if stock and str(stock).strip() else None

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute("""
            INSERT INTO products (user_id, name, price, category, quantity)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, name, price, category, quantity if quantity is not None else None))
        pid = cursor.lastrowid
        db.commit()
        log_audit(user_id, session.get('username', ''), 'CREATE', 'products',
                  pid, new_values={'name': name, 'price': price})
        cursor.close()
        db.close()

        return jsonify({
            'success': True,
            'id': pid,
            'name': name,
            'price': price,
            'category': category,
            'quantity': quantity,
            'message': f'{name} added'
        })

    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500

@quick_tap_bp.route('/quick-tap/products/update', methods=['POST'])
def update_product():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    user_id = session['user_id']
    data = request.get_json()
    product_id = data.get('id')
    name = data.get('name', '').strip()
    price = float(data.get('price', 0))
    category = data.get('category', '').strip() or None
    stock = data.get('stock')

    if not product_id or not name or price <= 0:
        return jsonify({'success': False, 'error': 'Invalid data'}), 400

    quantity = int(stock) if stock and str(stock).strip() else None

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute("""
            UPDATE products 
            SET name = %s, price = %s, category = %s, quantity = %s
            WHERE id = %s AND user_id = %s
        """, (name, price, category, quantity if quantity is not None else None, product_id, user_id))
        db.commit()
        log_audit(user_id, session.get('username', ''), 'UPDATE', 'products',
                  product_id, new_values={'name': name, 'price': price})
        log_audit(user_id, session.get('username', ''), 'UPDATE', 'products', 
                product_id, new_values={'name': name, 'price': price})
        cursor.close()
        db.close()

        return jsonify({'success': True, 'message': f'{name} updated'})

    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500

@quick_tap_bp.route('/quick-tap/products/delete', methods=['POST'])
def delete_product():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    user_id = session['user_id']
    data = request.get_json()
    product_id = data.get('id')

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute("UPDATE products SET deleted_at = NOW() WHERE id = %s AND user_id = %s", (product_id, user_id))
        db.commit()
        log_audit(user_id, session.get('username', ''), 'DELETE', 'products',
                  product_id, old_values={'deleted': True})
        log_audit(user_id, session.get('username', ''), 'DELETE', 'products', 
                product_id, old_values={'deleted': True})
        cursor.close()
        db.close()

        return jsonify({'success': True, 'message': 'Product removed'})

    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500

@quick_tap_bp.route('/quick-tap/products/import', methods=['POST'])
def import_products_csv():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    user_id = session['user_id']
    file = request.files.get('csv_file')

    if not file:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    try:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        reader = csv.DictReader(stream)
        imported = 0
        db = get_db()
        cursor = db.cursor()

        for row in reader:
            name = row.get('name', '').strip()
            price_str = row.get('price', '0').strip()
            stock_str = row.get('stock', '').strip()

            if not name or not price_str:
                continue

            price = float(price_str)
            if price <= 0:
                continue

            stock = int(stock_str) if stock_str else None

            if stock is not None:
                cursor.execute("INSERT INTO products (user_id, name, price, quantity) VALUES (%s, %s, %s, %s)", (user_id, name, price, stock))
            else:
                cursor.execute("INSERT INTO products (user_id, name, price) VALUES (%s, %s, %s)", (user_id, name, price))
            imported += 1

        db.commit()
        cursor.close()
        db.close()

        return jsonify({'success': True, 'message': f'{imported} products imported', 'count': imported})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@quick_tap_bp.route('/quick-tap/note', methods=['POST'])
def save_note():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    user_id = session['user_id']
    data = request.get_json()
    note_text = data.get('note', '').strip()

    if not note_text:
        return jsonify({'success': False, 'error': 'Write something'}), 400

    db = get_db()
    cursor = db.cursor()
    today = date.today()

    try:
        cursor.execute("""
            INSERT INTO transactions (user_id, amount, type, description, category, transaction_date, branch_id)
            VALUES (%s, 0, 'note', %s, 'Note', %s, %s)
        """, (user_id, note_text, today, session.get('branch_id')))
        db.commit()
        log_audit(user_id, session.get('username', ''), 'CREATE', 'notes',
                  cursor.lastrowid, new_values={'note': note_text[:100]})
        log_audit(user_id, session.get('username', ''), 'CREATE', 'notes', 
                cursor.lastrowid, new_values={'note': note_text[:100]})
        cursor.close()
        db.close()

        return jsonify({'success': True, 'message': 'Note saved'})

    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500

# ────────────────────────────────────────────────────────────
# ROUTES — CREDIT LIST
# ────────────────────────────────────────────────────────────

@quick_tap_bp.route('/quick-tap/credit')
def credit_page():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT i.id, c.name as customer_name, i.amount, i.description, i.status, 
               DATE(i.created_at) as invoice_date,
               COALESCE(SUM(p.amount), 0) as paid
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        LEFT JOIN payments p ON i.id = p.invoice_id
        WHERE i.user_id = %s AND i.status IN ('unpaid', 'overdue') AND i.deleted_at IS NULL
        GROUP BY i.id
        ORDER BY i.created_at DESC
    """, (user_id,))
    credits = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('quick_tap_credit.html', credits=credits, summary=get_today_summary(user_id))


# ────────────────────────────────────────────────────────────
# ROUTES — WEEKLY SUMMARY
# ────────────────────────────────────────────────────────────

@quick_tap_bp.route('/quick-tap/weekly')
def weekly_summary():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    return render_template('quick_tap_weekly.html', weekly=get_weekly_summary(session['user_id']))