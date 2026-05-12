from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from models.database import get_db
from models.audit import log_audit
from datetime import datetime

approvals_bp = Blueprint('approvals', __name__)

@approvals_bp.route('/approvals')
def view_approvals():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    # Only owner, admin, manager can approve
    if session.get('role') not in ['owner', 'admin', 'manager']:
        flash('You do not have permission to approve transactions.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    # Get pending transactions
    cursor.execute("""
        SELECT t.*, u.username as submitted_by_name
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s AND t.status = 'pending_approval' AND t.deleted_at IS NULL
        ORDER BY t.created_at DESC
    """, (business_id,))
    pending = cursor.fetchall()
    
    # Get recently approved/rejected
    cursor.execute("""
        SELECT t.*, u.username as submitted_by_name,
               au.username as approved_by_name
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        LEFT JOIN users au ON t.approved_by = au.id
        WHERE u.business_id = %s AND t.status IN ('approved', 'rejected') AND t.deleted_at IS NULL
        ORDER BY t.approved_at DESC
        LIMIT 20
    """, (business_id,))
    history = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('approvals.html', pending=pending, history=history)


@approvals_bp.route('/approvals/<int:transaction_id>/approve', methods=['POST'])
def approve_transaction(transaction_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('role') not in ['owner', 'admin', 'manager']:
        flash('You do not have permission to approve.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM transactions WHERE id = %s", (transaction_id,))
    txn = cursor.fetchone()
    
    if not txn or txn['status'] != 'pending_approval':
        flash('Transaction not found or already processed.', 'error')
        return redirect(url_for('approvals.view_approvals'))
    
    now = datetime.now()
    cursor.execute("""
        UPDATE transactions SET status = 'approved', approved_by = %s, approved_at = %s
        WHERE id = %s
    """, (session['user_id'], now, transaction_id))
    
    # Create journal entries for approved transaction
    if session.get('plan') in ['professional', 'suite']:
        cursor.execute("""
            SELECT debit_account_id, credit_account_id FROM transaction_account_mapping
            WHERE transaction_type = %s AND (category = %s OR category IS NULL)
            ORDER BY category IS NULL LIMIT 1
        """, (txn['type'], txn['category'] or ''))
        mapping = cursor.fetchone()
        
        if mapping:
            cursor.execute("""
                INSERT INTO journal_entries (user_id, entry_date, description, reference)
                VALUES (%s, %s, %s, %s)
            """, (txn['user_id'], txn['transaction_date'], txn['description'], f"TRX-{transaction_id}"))
            journal_id = cursor.lastrowid
            
            amount = float(txn['amount'])
            if txn['type'] == 'income':
                cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, %s, %s, 0)", (journal_id, mapping[0], amount))
                cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, %s, 0, %s)", (journal_id, mapping[1], amount))
            else:
                cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, %s, %s, 0)", (journal_id, mapping[0], amount))
                cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s, %s, 0, %s)", (journal_id, mapping[1], amount))
    
    db.commit()
    
    log_audit(session['user_id'], session['username'], 'APPROVE', 'transactions',
              transaction_id, new_values={'status': 'approved', 'approved_at': str(now)})
    
    cursor.close()
    db.close()
    
    flash(f'Transaction approved: {txn["description"]} — ₱{float(txn["amount"]):,.2f}', 'success')
    return redirect(url_for('approvals.view_approvals'))


@approvals_bp.route('/approvals/<int:transaction_id>/reject', methods=['POST'])
def reject_transaction(transaction_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('role') not in ['owner', 'admin', 'manager']:
        flash('You do not have permission to reject.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    reason = request.form.get('reason', 'No reason provided')
    
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        UPDATE transactions SET status = 'rejected', approved_by = %s, 
        approved_at = NOW(), rejection_reason = %s
        WHERE id = %s AND status = 'pending_approval'
    """, (session['user_id'], reason, transaction_id))
    db.commit()
    
    log_audit(session['user_id'], session['username'], 'REJECT', 'transactions',
              transaction_id, new_values={'status': 'rejected', 'reason': reason})
    
    cursor.close()
    db.close()
    
    flash('Transaction rejected.', 'info')
    return redirect(url_for('approvals.view_approvals'))

