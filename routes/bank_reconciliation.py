from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date, timedelta
import csv
import io
from models.database import get_db
from models.access_control import check_module_access

bank_rec_bp = Blueprint('bank_rec', __name__)

@bank_rec_bp.route('/bank-reconciliation')
def bank_reconciliation():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    if not check_module_access('bank_reconciliation'): return redirect(url_for('dashboard.dashboard'))

    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    # Get all reconciliations
    cursor.execute("""
        SELECT * FROM bank_reconciliations
        WHERE user_id = %s
        ORDER BY statement_date DESC
    """, (session['user_id'],))
    reconciliations = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('bank_reconciliation.html',
                         username=session['username'],
                         reconciliations=reconciliations,
                         today=date.today().isoformat())


@bank_rec_bp.route('/new_reconciliation', methods=['POST'])
def new_reconciliation():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    bank_name = request.form.get('bank_name', '')
    statement_date = request.form.get('statement_date', date.today())
    opening_balance = float(request.form.get('opening_balance', 0))
    closing_balance = float(request.form.get('closing_balance', 0))
    
    bank_file = request.files.get('bank_csv')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    # Create reconciliation record
    cursor.execute("""
        INSERT INTO bank_reconciliations (user_id, bank_name, statement_date, opening_balance, closing_balance)
        VALUES (%s, %s, %s, %s, %s)
    """, (session['user_id'], bank_name, statement_date, opening_balance, closing_balance))
    rec_id = cursor.lastrowid
    
    # Get all TARA transactions for the period
    cursor.execute("""
        SELECT t.id, t.description, t.amount, t.type, t.transaction_date as date
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.transaction_date <= %s AND t.deleted_at IS NULL
        ORDER BY t.transaction_date DESC
    """, (business_id, statement_date))
    tara_transactions = cursor.fetchall()
    
    # Add TARA transactions as source='tara'
    for tx in tara_transactions:
        cursor.execute("""
            INSERT INTO reconciliation_items (reconciliation_id, transaction_id, description, amount, type, source)
            VALUES (%s, %s, %s, %s, %s, 'tara')
        """, (rec_id, tx['id'], tx['description'], float(tx['amount']),
              'deposit' if tx['type'] == 'income' else 'withdrawal'))
    
    # Parse bank CSV if uploaded
    if bank_file and bank_file.filename.endswith('.csv'):
        stream = io.StringIO(bank_file.stream.read().decode("UTF8"), newline=None)
        reader = csv.DictReader(stream)
        
        for row in reader:
            try:
                bank_amount = abs(float(row.get('Amount', '0')))
                bank_type = 'deposit' if float(row.get('Amount', 0)) > 0 else 'withdrawal'
                bank_desc = row.get('Description', 'Bank transaction')
                bank_date = row.get('Date', '')
                
                cursor.execute("""
                    INSERT INTO reconciliation_items (reconciliation_id, description, amount, type, source)
                    VALUES (%s, %s, %s, %s, 'bank')
                """, (rec_id, f"[{bank_date}] {bank_desc}", bank_amount, bank_type))
            except:
                pass
    
    # Auto-match: same amount + type
    cursor.execute("""
        SELECT * FROM reconciliation_items
        WHERE reconciliation_id = %s AND source = 'tara' AND matched = FALSE
    """, (rec_id,))
    tara_items = cursor.fetchall()
    
    cursor.execute("""
        SELECT * FROM reconciliation_items
        WHERE reconciliation_id = %s AND source = 'bank' AND matched = FALSE
    """, (rec_id,))
    bank_items = cursor.fetchall()
    
    matched_count = 0
    for t_item in tara_items:
        for b_item in bank_items:
            if (float(t_item['amount']) == float(b_item['amount']) and 
                t_item['type'] == b_item['type'] and
                not b_item['matched']):
                cursor.execute("""
                    UPDATE reconciliation_items SET matched = TRUE, source = 'both',
                    transaction_id = %s WHERE id = %s
                """, (t_item['transaction_id'], b_item['id']))
                cursor.execute("""
                    UPDATE reconciliation_items SET matched = TRUE, source = 'both'
                    WHERE id = %s
                """, (t_item['id'],))
                b_item['matched'] = True
                matched_count += 1
                break
    
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Reconciliation created! {matched_count} transactions auto-matched.', 'success')
    return redirect(url_for('bank_rec.view_reconciliation', rec_id=rec_id))


@bank_rec_bp.route('/reconciliation/<int:rec_id>')
def view_reconciliation(rec_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM bank_reconciliations WHERE id = %s", (rec_id,))
    rec = cursor.fetchone()
    
    if not rec:
        cursor.close()
        db.close()
        flash('Reconciliation not found.', 'error')
        return redirect(url_for('bank_rec.bank_reconciliation'))
    
    # Matched items
    cursor.execute("""
        SELECT * FROM reconciliation_items
        WHERE reconciliation_id = %s AND matched = TRUE
        ORDER BY amount DESC
    """, (rec_id,))
    matched = cursor.fetchall()
    
    # Unmatched TARA
    cursor.execute("""
        SELECT * FROM reconciliation_items
        WHERE reconciliation_id = %s AND source = 'tara' AND matched = FALSE
        ORDER BY amount DESC
    """, (rec_id,))
    unmatched_tara = cursor.fetchall()
    
    # Unmatched Bank
    cursor.execute("""
        SELECT * FROM reconciliation_items
        WHERE reconciliation_id = %s AND source = 'bank' AND matched = FALSE
        ORDER BY amount DESC
    """, (rec_id,))
    unmatched_bank = cursor.fetchall()
    
    # Totals
    total_matched = sum(float(i['amount']) for i in matched if i['type'] == 'deposit') - sum(float(i['amount']) for i in matched if i['type'] == 'withdrawal')
    total_unmatched_tara = sum(float(i['amount']) for i in unmatched_tara if i['type'] == 'deposit') - sum(float(i['amount']) for i in unmatched_tara if i['type'] == 'withdrawal')
    total_unmatched_bank = sum(float(i['amount']) for i in unmatched_bank if i['type'] == 'deposit') - sum(float(i['amount']) for i in unmatched_bank if i['type'] == 'withdrawal')
    
    cursor.close()
    db.close()
    
    return render_template('reconciliation_view.html',
                         username=session['username'],
                         rec=rec,
                         matched=matched,
                         unmatched_tara=unmatched_tara,
                         unmatched_bank=unmatched_bank,
                         total_matched=total_matched,
                         total_unmatched_tara=total_unmatched_tara,
                         total_unmatched_bank=total_unmatched_bank)