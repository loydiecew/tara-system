from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from models.database import get_db
from datetime import date, datetime, timedelta
import json

quick_tap_bp = Blueprint('quick_tap', __name__)

# ────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────

def get_streak(user_id):
    """Calculate consecutive days with at least one sale."""
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

    if not dates:
        return 0
    if dates[0] != date.today():
        return 0

    streak = 1
    today = date.today()
    for i in range(1, len(dates)):
        expected = today - timedelta(days=i)
        if dates[i] == expected:
            streak += 1
        else:
            break
    return streak


def get_yesterday_comparison(user_id):
    """Compare today's sales vs yesterday's."""
    db = get_db()
    cursor = db.cursor()
    today = date.today()
    yesterday = today - timedelta(days=1)

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) FROM sales 
        WHERE user_id = %s AND sale_date = %s AND deleted_at IS NULL
    """, (user_id, today))
    today_total = float(cursor.fetchone()[0])

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) FROM sales 
        WHERE user_id = %s AND sale_date = %s AND deleted_at IS NULL
    """, (user_id, yesterday))
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
    """Get today's sales, expenses, and utang totals."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    today = date.today()

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total FROM sales
        WHERE user_id = %s AND sale_date = %s AND deleted_at IS NULL
    """, (user_id, today))
    sales_total = float(cursor.fetchone()['total'])

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total FROM transactions
        WHERE user_id = %s AND transaction_date = %s AND type = 'expense' AND deleted_at IS NULL
    """, (user_id, today))
    expense_total = float(cursor.fetchone()['total'])

    # Utang recorded today — join with customers table to get name
    cursor.execute("""
        SELECT COALESCE(SUM(i.amount), 0) as total FROM invoices i
        WHERE i.user_id = %s AND DATE(i.created_at) = %s AND i.deleted_at IS NULL
    """, (user_id, today))
    utang_today = float(cursor.fetchone()['total'])

    # Utang collected today
    cursor.execute("""
        SELECT COALESCE(SUM(p.amount), 0) as total 
        FROM payments p
        JOIN invoices i ON p.invoice_id = i.id
        WHERE i.user_id = %s AND DATE(p.payment_date) = %s
    """, (user_id, today))
    utang_collected = float(cursor.fetchone()['total'])

    # Total outstanding utang
    cursor.execute("""
        SELECT COALESCE(SUM(i.amount), 0) - COALESCE(SUM(p.amount), 0) as outstanding
        FROM invoices i
        LEFT JOIN payments p ON i.id = p.invoice_id
        WHERE i.user_id = %s AND i.status IN ('unpaid', 'overdue') AND i.deleted_at IS NULL
    """, (user_id,))
    utang_outstanding = float(cursor.fetchone()['outstanding'])
    cursor.close()
    db.close()

    return {
        'sales_total': sales_total,
        'expense_total': expense_total,
        'profit': sales_total - expense_total,
        'utang_today': utang_today,
        'utang_collected': utang_collected,
        'utang_outstanding': utang_outstanding
    }


def get_best_day(user_id):
    """Find the best sales day this month."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    first_of_month = date.today().replace(day=1)

    cursor.execute("""
        SELECT sale_date, SUM(amount) as total FROM sales
        WHERE user_id = %s AND sale_date >= %s AND deleted_at IS NULL
        GROUP BY sale_date ORDER BY total DESC LIMIT 1
    """, (user_id, first_of_month))
    result = cursor.fetchone()
    cursor.close()
    db.close()
    return result


def get_weekly_summary(user_id):
    """Get summary for the current week (Mon-Sun)."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total_sales, COUNT(*) as txns
        FROM sales WHERE user_id = %s AND sale_date >= %s AND sale_date <= %s AND deleted_at IS NULL
    """, (user_id, monday, today))
    sales = cursor.fetchone()

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) as total_expenses
        FROM transactions WHERE user_id = %s AND transaction_date >= %s AND transaction_date <= %s AND type = 'expense' AND deleted_at IS NULL
    """, (user_id, monday, today))
    expenses = cursor.fetchone()

    # Best product this week
    cursor.execute("""
        SELECT si.product_name, SUM(si.amount) as total
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE s.user_id = %s AND s.sale_date >= %s AND s.sale_date <= %s AND s.deleted_at IS NULL
        GROUP BY si.product_name ORDER BY total DESC LIMIT 1
    """, (user_id, monday, today))
    best_product = cursor.fetchone()

    cursor.close()
    db.close()

    return {
        'total_sales': float(sales['total_sales']),
        'total_expenses': float(expenses['total_expenses']),
        'profit': float(sales['total_sales']) - float(expenses['total_expenses']),
        'transaction_count': sales['txns'],
        'best_product': best_product['product_name'] if best_product else None,
        'best_product_amount': float(best_product['total']) if best_product else 0,
        'week_start': monday,
        'week_end': today
    }


# ────────────────────────────────────────────────────────────
# ROUTES
# ────────────────────────────────────────────────────────────

@quick_tap_bp.route('/quick-tap')
def index():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Get products for button grid (top 12 by name)
    cursor.execute("""
        SELECT id, name, price, quantity FROM products
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY name LIMIT 12
    """, (user_id,))
    products = cursor.fetchall()
    cursor.close()
    db.close()

    streak = get_streak(user_id)
    comparison = get_yesterday_comparison(user_id)
    summary = get_today_summary(user_id)
    best_day = get_best_day(user_id)
    weekly = get_weekly_summary(user_id)

    # Recent activity
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        (SELECT 'sale' as type, s.description as name, s.amount, s.created_at as ts
         FROM sales s WHERE s.user_id = %s AND s.sale_date = %s AND s.deleted_at IS NULL)
        UNION ALL
        (SELECT 'expense' as type, t.description as name, t.amount, t.created_at as ts
         FROM transactions t WHERE t.user_id = %s AND t.transaction_date = %s AND t.type = 'expense' AND t.deleted_at IS NULL)
        UNION ALL
        (SELECT 'utang' as type, CONCAT(c.name, ' — ', COALESCE(i.description, 'Utang')) as name, i.amount, i.created_at as ts
         FROM invoices i JOIN customers c ON i.customer_id = c.id
         WHERE i.user_id = %s AND DATE(i.created_at) = %s AND i.deleted_at IS NULL)
        ORDER BY ts DESC LIMIT 20
    """, (user_id, date.today(), user_id, date.today(), user_id, date.today()))
    activity = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template('quick_tap.html',
                           products=products,
                           streak=streak,
                           comparison=comparison,
                           summary=summary,
                           best_day=best_day,
                           weekly=weekly,
                           activity=activity,
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
        desc = f"[QT] {product_name}" + (f" x{quantity}" if quantity > 1 else "")

        # Sale
        cursor.execute("""
            INSERT INTO sales (user_id, customer_name, amount, sale_date, description, payment_method, branch_id)
            VALUES (%s, 'Walk-in', %s, %s, %s, 'cash', %s)
        """, (user_id, amount, today, desc, session.get('branch_id')))
        sale_id = cursor.lastrowid

        # Sale item
        cursor.execute("""
            INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, amount)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (sale_id, product_id, product_name, quantity, amount / quantity, amount))

        # Cash transaction
        cursor.execute("""
            INSERT INTO transactions (user_id, amount, type, description, category, transaction_date, payment_method, branch_id)
            VALUES (%s, %s, 'income', %s, 'Sales', %s, 'cash', %s)
        """, (user_id, amount, desc, today, session.get('branch_id')))

        # Journal entry
        cursor.execute("""
            INSERT INTO journal_entries (user_id, entry_date, description, reference)
            VALUES (%s, %s, %s, %s)
        """, (user_id, today, f"Quick Tap: {product_name}", f"QT-{sale_id}"))
        journal_id = cursor.lastrowid

        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 1, %s, 0)", (journal_id, amount))
        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 6, 0, %s)", (journal_id, amount))

        # Inventory deduction
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

        streak = get_streak(user_id)
        comparison = get_yesterday_comparison(user_id)
        summary = get_today_summary(user_id)

        cursor.close()
        db.close()

        return jsonify({
            'success': True,
            'sale_id': sale_id,
            'amount': amount,
            'product_name': product_name,
            'streak': streak,
            'comparison': comparison,
            'summary': summary,
            'message': f'{product_name} — ₱{amount:,.0f}'
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
        cursor.execute("""
            INSERT INTO transactions (user_id, amount, type, description, category, transaction_date, branch_id)
            VALUES (%s, %s, 'expense', %s, %s, %s, %s)
        """, (user_id, amount, description, category, today, session.get('branch_id')))

        cursor.execute("""
            INSERT INTO journal_entries (user_id, entry_date, description, reference)
            VALUES (%s, %s, %s, %s)
        """, (user_id, today, f"Expense: {description}", f"EXP-{cursor.lastrowid}"))
        journal_id = cursor.lastrowid

        expense_account_map = {'Rent': 9, 'Utilities': 10, 'Supplies': 11, 'Salary': 12, 'General': 11}
        account_id = expense_account_map.get(category, 11)

        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, %s, %s, 0)", (journal_id, account_id, amount))
        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 1, 0, %s)", (journal_id, amount))

        db.commit()
        cursor.close()
        db.close()

        summary = get_today_summary(user_id)

        return jsonify({
            'success': True,
            'amount': amount,
            'description': description,
            'summary': summary,
            'message': f'Expense ₱{amount:,.0f} recorded'
        })

    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500


@quick_tap_bp.route('/quick-tap/utang', methods=['POST'])
def record_utang():
    """Record a utang (AR) entry — simple name + amount, no invoice numbers."""
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
        # Create or get customer
        cursor.execute("SELECT id FROM customers WHERE user_id = %s AND name = %s AND deleted_at IS NULL", (user_id, customer_name))
        cust = cursor.fetchone()

        if cust:
            customer_id = cust[0]
        else:
            cursor.execute("INSERT INTO customers (user_id, name) VALUES (%s, %s)", (user_id, customer_name))
            customer_id = cursor.lastrowid

        # Create invoice linked to customer
        desc = f"Utang: {item}" if item else "Utang"
        cursor.execute("""
            INSERT INTO invoices (user_id, customer_id, amount, description, status, due_date)
            VALUES (%s, %s, %s, %s, 'unpaid', DATE_ADD(CURDATE(), INTERVAL 30 DAY))
        """, (user_id, customer_id, amount, desc))

        db.commit()
        cursor.close()
        db.close()

        summary = get_today_summary(user_id)

        return jsonify({
            'success': True,
            'customer_name': customer_name,
            'amount': amount,
            'summary': summary,
            'message': f'{customer_name} utang ₱{amount:,.0f}'
        })

    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500


@quick_tap_bp.route('/quick-tap/utang/pay', methods=['POST'])
def pay_utang():
    """Record a payment toward utang."""
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
        cursor.execute("SELECT * FROM invoices WHERE id = %s AND user_id = %s AND deleted_at IS NULL", (invoice_id, user_id))
        invoice = cursor.fetchone()
        if not invoice:
            cursor.close()
            db.close()
            return jsonify({'success': False, 'error': 'Invoice not found'}), 404

        # Record payment
        cursor.execute("""
            INSERT INTO payments (invoice_id, amount, payment_date, payment_method)
            VALUES (%s, %s, CURDATE(), 'cash')
        """, (invoice_id, amount))

        # Check if fully paid
        cursor.execute("SELECT COALESCE(SUM(amount), 0) as total_paid FROM payments WHERE invoice_id = %s", (invoice_id,))
        paid = float(cursor.fetchone()['total_paid'])

        new_status = 'paid' if paid >= float(invoice['amount']) else 'unpaid'
        cursor.execute("UPDATE invoices SET status = %s WHERE id = %s", (new_status, invoice_id))

        db.commit()
        cursor.close()
        db.close()

        summary = get_today_summary(user_id)

        return jsonify({
            'success': True,
            'amount': amount,
            'customer_name': invoice['customer_name'],
            'summary': summary,
            'message': f'Received ₱{amount:,.0f} from {invoice["customer_name"]}'
        })

    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500


@quick_tap_bp.route('/quick-tap/utang/list')
def utang_list():
    """Get all outstanding utang for the current user."""
    if 'user_id' not in session:
        return jsonify([]), 401

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
    utangs = cursor.fetchall()
    cursor.close()
    db.close()

    return jsonify(utangs)


@quick_tap_bp.route('/quick-tap/reconciliation', methods=['GET', 'POST'])
def reconciliation():
    """End of day reconciliation screen."""
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

        expected_cash = recorded_sales - recorded_expenses
        micro_sales = actual_cash - expected_cash

        if micro_sales > 0:
            desc = "[QT] Micro Sales (Reconciliation)"
            cursor.execute("INSERT INTO sales (user_id, customer_name, amount, sale_date, description, payment_method, branch_id) VALUES (%s, 'Various', %s, %s, %s, 'cash', %s)",
                           (user_id, micro_sales, today, desc, session.get('branch_id')))
            sale_id = cursor.lastrowid
            cursor.execute("INSERT INTO sale_items (sale_id, product_id, product_name, quantity, unit_price, amount) VALUES (%s, NULL, 'Micro Sales', 1, %s, %s)",
                           (sale_id, micro_sales, micro_sales))
            cursor.execute("INSERT INTO transactions (user_id, amount, type, description, category, transaction_date, branch_id) VALUES (%s, %s, 'income', %s, 'Sales', %s, %s)",
                           (user_id, micro_sales, desc, today, session.get('branch_id')))
            cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description, reference) VALUES (%s, %s, %s, %s)",
                           (user_id, today, "Micro Sales Reconciliation", f"RECON-{today}"))
            jid = cursor.lastrowid
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 1, %s, 0)", (jid, micro_sales))
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 6, 0, %s)", (jid, micro_sales))

        elif micro_sales < 0:
            shortfall = abs(micro_sales)
            desc = "[QT] Cash Shortfall"
            cursor.execute("INSERT INTO transactions (user_id, amount, type, description, category, transaction_date, branch_id) VALUES (%s, %s, 'expense', %s, 'Cash Shortfall', %s, %s)",
                           (user_id, shortfall, desc, today, session.get('branch_id')))
            cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description, reference) VALUES (%s, %s, %s, %s)",
                           (user_id, today, "Cash Shortfall", f"RECON-{today}"))
            jid = cursor.lastrowid
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 11, %s, 0)", (jid, shortfall))
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, 1, 0, %s)", (jid, shortfall))

        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('quick_tap.index'))

    # GET
    summary = get_today_summary(user_id)
    return render_template('reconciliation.html', summary=summary, today=date.today())


@quick_tap_bp.route('/quick-tap/weekly')
def weekly_summary():
    """Weekly summary page."""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user_id = session['user_id']
    weekly = get_weekly_summary(user_id)

    return render_template('weekly_summary.html', weekly=weekly)