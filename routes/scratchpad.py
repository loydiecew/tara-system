"""
Scratchpad Parser Routes
POST /scratchpad/parse — accepts text, returns structured preview
POST /scratchpad/save  — saves the confirmed transaction
"""

from flask import Blueprint, request, jsonify, session, flash
from datetime import date, datetime
from utils.scratchpad_parser import parse
from models.database import get_db
from models.audit import log_audit

scratchpad_bp = Blueprint('scratchpad', __name__)


@scratchpad_bp.route('/scratchpad/parse', methods=['POST'])
def scratchpad_parse():
    """Parse freeform text and return a transaction preview."""
    data = request.get_json()
    text = data.get('text', '').strip()

    if not text:
        return jsonify({'success': False, 'error': 'No text provided'})

    result = parse(text)
    return jsonify(result)


@scratchpad_bp.route('/scratchpad/save', methods=['POST'])
def scratchpad_save():
    """Save a confirmed transaction from the scratchpad preview."""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'})

    data = request.get_json()
    txn_type = data.get('transaction_type', 'expense')
    amount = float(data.get('total_amount', 0))
    category = data.get('category', '')
    description = data.get('description', '')
    payment_method = data.get('payment_method', 'cash')
    person = data.get('person', '')
    items = data.get('items', [])
    txn_date = data.get('date', date.today().isoformat())

    if amount <= 0:
        return jsonify({'success': False, 'error': 'Amount must be greater than zero'})

    # Parse date string to date object
    if isinstance(txn_date, str):
        try:
            txn_date = datetime.fromisoformat(txn_date).date()
        except (ValueError, TypeError):
            txn_date = date.today()

    db = get_db()
    cursor = db.cursor()

    try:
        if txn_type == 'sale' and items:
            # ── Create a sale with items ──────────────────────
            # Build description from items
            item_descriptions = []
            for item in items:
                item_descriptions.append(f"{item.get('quantity', 1)}x {item.get('product', 'Item')}")
            sale_description = ', '.join(item_descriptions)

            cursor.execute("""
                INSERT INTO sales (user_id, customer_name, amount, sale_date, description,
                                  payment_method, discount_type, discount_value, discount_amount)
                VALUES (%s, %s, %s, %s, %s, %s, 'none', 0, 0)
            """, (session['user_id'], person or 'Walk-in Customer', amount, txn_date,
                  sale_description, payment_method))
            sale_id = cursor.lastrowid

            # Insert sale items
            for item in items:
                cursor.execute("""
                    INSERT INTO sale_items (sale_id, product_name, quantity, unit_price, amount,
                                           discount_percent, discount_amount)
                    VALUES (%s, %s, %s, %s, %s, 0, 0)
                """, (sale_id, item.get('product', 'Item'),
                      item.get('quantity', 1), item.get('unit_price', 0),
                      item.get('total', 0)))

            # Also create a cash transaction for the income
            cursor.execute("""
                INSERT INTO transactions (user_id, description, amount, type, category,
                                         transaction_date, reference_number, payment_method, status)
                VALUES (%s, %s, %s, 'income', %s, %s, '', %s, 'active')
            """, (session['user_id'], f"Sale: {sale_description}", amount,
                  category or 'Sales', txn_date, payment_method))

            # Journal entry for Pro+ users
            if session.get('plan') in ['professional', 'suite']:
                cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '1000'")
                cash_account = cursor.fetchone()
                cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '4000'")
                revenue_account = cursor.fetchone()
                if cash_account and revenue_account:
                    cursor.execute("""
                        INSERT INTO journal_entries (user_id, entry_date, description)
                        VALUES (%s, %s, %s)
                    """, (session['user_id'], txn_date,
                          f"Sale to {person or 'Customer'} - {sale_description}"))
                    entry_id = cursor.lastrowid
                    cursor.execute("""
                        INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
                        VALUES (%s, %s, %s, 0)
                    """, (entry_id, cash_account[0], amount))
                    cursor.execute("""
                        INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
                        VALUES (%s, %s, 0, %s)
                    """, (entry_id, revenue_account[0], amount))

            db.commit()
            log_audit(session['user_id'], session.get('username', ''), 'CREATE', 'sales',
                     sale_id, new_values={'description': sale_description, 'amount': amount})

            return jsonify({'success': True, 'message': f'Sale recorded: ₱{amount:,.2f}'})

        elif txn_type == 'expense':
            # ── Create an expense transaction ─────────────────
            cursor.execute("""
                INSERT INTO transactions (user_id, description, amount, type, category,
                                         transaction_date, reference_number, payment_method, status)
                VALUES (%s, %s, %s, 'expense', %s, %s, '', %s, 'active')
            """, (session['user_id'], description, amount,
                  category or 'Uncategorized', txn_date, payment_method))

            txn_id = cursor.lastrowid

            # Journal entry for Pro+ users
            if session.get('plan') in ['professional', 'suite']:
                cursor.execute("""
                    SELECT debit_account_id, credit_account_id FROM transaction_account_mapping
                    WHERE transaction_type = 'expense' AND (category = %s OR category IS NULL)
                    ORDER BY category IS NULL LIMIT 1
                """, (category,))
                mapping = cursor.fetchone()
                if mapping:
                    cursor.execute("""
                        INSERT INTO journal_entries (user_id, entry_date, description, reference)
                        VALUES (%s, %s, %s, %s)
                    """, (session['user_id'], txn_date, description, f"TRX-{txn_id}"))
                    entry_id = cursor.lastrowid
                    cursor.execute("""
                        INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
                        VALUES (%s, %s, %s, 0)
                    """, (entry_id, mapping[0], amount))
                    cursor.execute("""
                        INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit)
                        VALUES (%s, %s, 0, %s)
                    """, (entry_id, mapping[1], amount))

            db.commit()
            log_audit(session['user_id'], session.get('username', ''), 'CREATE', 'transactions',
                     txn_id, new_values={'description': description, 'amount': amount, 'category': category})

            return jsonify({'success': True, 'message': f'Expense recorded: ₱{amount:,.2f}'})

        elif txn_type == 'payment_received':
            # ── Record a payment received ─────────────────────
            # First, check if there's a matching customer
            cursor.execute("SELECT id FROM customers WHERE name = %s AND user_id = %s",
                          (person, session['user_id']))
            customer = cursor.fetchone()

            if not customer and person:
                cursor.execute("""
                    INSERT INTO customers (user_id, name) VALUES (%s, %s)
                """, (session['user_id'], person))
                customer_id = cursor.lastrowid
            elif customer:
                customer_id = customer[0]
            else:
                customer_id = None

            # Create a general payment (not tied to a specific invoice)
            # This creates a cash income transaction
            cursor.execute("""
                INSERT INTO transactions (user_id, description, amount, type, category,
                                         transaction_date, reference_number, payment_method, status)
                VALUES (%s, %s, %s, 'income', %s, %s, '', %s, 'active')
            """, (session['user_id'],
                  f"Payment received from {person}" if person else description,
                  amount,
                  'Accounts Receivable' if customer_id else 'Other Income',
                  txn_date, payment_method))

            txn_id = cursor.lastrowid

            # If we have a customer, also create a payment record
            if customer_id:
                cursor.execute("""
                    INSERT INTO payments (user_id, invoice_id, amount, payment_date,
                                         payment_method, reference_number, notes)
                    VALUES (%s, NULL, %s, %s, %s, '', %s)
                """, (session['user_id'], amount, txn_date, payment_method, description))

            db.commit()
            log_audit(session['user_id'], session.get('username', ''), 'CREATE', 'transactions',
                     txn_id, new_values={'description': description, 'amount': amount})

            return jsonify({'success': True, 'message': f'Payment recorded: ₱{amount:,.2f}'})

        else:
            # ── Fallback: create as expense ──────────────────
            cursor.execute("""
                INSERT INTO transactions (user_id, description, amount, type, category,
                                         transaction_date, reference_number, payment_method, status)
                VALUES (%s, %s, %s, 'expense', %s, %s, '', %s, 'active')
            """, (session['user_id'], description, amount,
                  category or 'Uncategorized', txn_date, payment_method or 'cash'))

            txn_id = cursor.lastrowid
            db.commit()
            log_audit(session['user_id'], session.get('username', ''), 'CREATE', 'transactions',
                     txn_id, new_values={'description': description, 'amount': amount})

            return jsonify({'success': True, 'message': f'Transaction recorded: ₱{amount:,.2f}'})

    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cursor.close()
        db.close()