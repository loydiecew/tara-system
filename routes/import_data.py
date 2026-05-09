from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date
import csv
import io
from models.database import get_db

import_bp = Blueprint('import_data', __name__)

ALLOWED_MODULES = ['cash', 'sales', 'inventory', 'customers', 'suppliers', 'bills', 'invoices', 'po', 'so', 'opening_balances']

@import_bp.route('/import-data', methods=['GET', 'POST'])
def import_data():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('role') == 'cashier':
        flash('Only admins and managers can import data', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    preview = []
    imported = 0
    skipped = 0
    active_tab = request.args.get('tab', 'cash')
    
    if request.method == 'POST':
        active_tab = request.form.get('module', 'cash')
        confirm = request.form.get('confirm') == 'true'
        file_content = None
        
        if confirm:
            stored = session.pop('csv_data', {})
            file_content = stored.get('content', '')
            if not file_content:
                flash('No file data found. Please re-upload.', 'error')
                return redirect(url_for('import_data.import_data', tab=active_tab))
        else:
            if 'csv_file' not in request.files:
                flash('No file selected', 'error')
                return redirect(url_for('import_data.import_data', tab=active_tab))
            file = request.files['csv_file']
            if file.filename == '':
                flash('No file selected', 'error')
                return redirect(url_for('import_data.import_data', tab=active_tab))
            if not file.filename.endswith('.csv'):
                flash('Please upload a CSV file', 'error')
                return redirect(url_for('import_data.import_data', tab=active_tab))
            file_content = file.stream.read().decode("UTF8")
            session['csv_data'] = {'content': file_content, 'module': active_tab}
        
        stream = io.StringIO(file_content, newline=None)
        reader = csv.DictReader(stream)
        
        for row_num, row in enumerate(reader, start=2):
            row['_row'] = row_num
            row['_status'] = 'valid'
            row['_error'] = ''
            
            if active_tab == 'cash': validate_cash_row(row)
            elif active_tab == 'sales': validate_sales_row(row)
            elif active_tab == 'inventory': validate_inventory_row(row)
            elif active_tab == 'customers': validate_customer_row(row)
            elif active_tab == 'suppliers': validate_supplier_row(row)
            elif active_tab == 'bills': validate_bill_row(row)
            elif active_tab == 'invoices': validate_invoice_row(row)
            elif active_tab == 'po': validate_po_row(row)
            elif active_tab == 'so': validate_so_row(row)
            elif active_tab == 'opening_balances': validate_opening_balance_row(row)
            
            if row['_status'] == 'valid' and confirm:
                try:
                    import_row(active_tab, row)
                    imported += 1
                except Exception as e:
                    row['_status'] = 'error'
                    row['_error'] = str(e)
                    skipped += 1
            elif row['_status'] != 'valid':
                skipped += 1
            preview.append(row)
        
        if confirm:
            flash(f'{imported} imported, {skipped} skipped.' if imported > 0 else f'No records imported. {skipped} skipped.', 'success' if imported > 0 else 'error')
            return redirect(url_for('import_data.import_data', tab=active_tab))
        
        return render_template('import_preview.html', preview=preview, active_tab=active_tab, imported=imported, skipped=skipped, show_import_btn=any(r['_status']=='valid' for r in preview))
    
    return render_template('import_data.html', username=session['username'], active_tab=active_tab)

# ========== VALIDATION FUNCTIONS ==========

def validate_cash_row(row):
    if not row.get('Date','').strip(): row['_status'],row['_error']='error','Date required';return
    try: date.fromisoformat(row['Date'].strip())
    except: row['_status'],row['_error']='error','Invalid date (YYYY-MM-DD)';return
    if not row.get('Description','').strip(): row['_status'],row['_error']='error','Description required';return
    try:
        if float(row.get('Amount','0').strip())<=0: raise ValueError
    except: row['_status'],row['_error']='error','Amount must be positive';return
    if row.get('Type','').strip().lower() not in ['income','expense']: row['_status'],row['_error']='error','Type: income or expense';return

def validate_sales_row(row):
    if not row.get('Date','').strip(): row['_status'],row['_error']='error','Date required';return
    try: date.fromisoformat(row['Date'].strip())
    except: row['_status'],row['_error']='error','Invalid date';return
    if not row.get('Customer','').strip(): row['_status'],row['_error']='error','Customer required';return
    try:
        if float(row.get('Amount','0').strip())<=0: raise ValueError
    except: row['_status'],row['_error']='error','Amount must be positive';return

def validate_inventory_row(row):
    if not row.get('Name','').strip(): row['_status'],row['_error']='error','Name required';return
    try:
        if float(row.get('Price','0').strip())<0: raise ValueError
    except: row['_status'],row['_error']='error','Invalid price';return
    try:
        if int(row.get('Quantity','0').strip())<0: raise ValueError
    except: row['_status'],row['_error']='error','Invalid quantity';return

def validate_customer_row(row):
    if not row.get('Name','').strip(): row['_status'],row['_error']='error','Name required';return

def validate_supplier_row(row):
    if not row.get('Name','').strip(): row['_status'],row['_error']='error','Name required';return

def validate_bill_row(row):
    if not row.get('Supplier','').strip(): row['_status'],row['_error']='error','Supplier required';return
    try:
        if float(row.get('Amount','0').strip())<=0: raise ValueError
    except: row['_status'],row['_error']='error','Amount must be positive';return
    if not row.get('Due_Date','').strip(): row['_status'],row['_error']='error','Due Date required';return

def validate_invoice_row(row):
    if not row.get('Customer','').strip(): row['_status'],row['_error']='error','Customer required';return
    try:
        if float(row.get('Amount','0').strip())<=0: raise ValueError
    except: row['_status'],row['_error']='error','Amount must be positive';return
    if not row.get('Due_Date','').strip(): row['_status'],row['_error']='error','Due Date required';return

def validate_po_row(row):
    if not row.get('Supplier','').strip(): row['_status'],row['_error']='error','Supplier required';return
    if not row.get('Item','').strip(): row['_status'],row['_error']='error','Item required';return
    try:
        if int(row.get('Qty','0').strip())<=0: raise ValueError
    except: row['_status'],row['_error']='error','Qty must be positive';return

def validate_so_row(row):
    if not row.get('Customer','').strip(): row['_status'],row['_error']='error','Customer required';return
    if not row.get('Item','').strip(): row['_status'],row['_error']='error','Item required';return
    try:
        if int(row.get('Qty','0').strip())<=0: raise ValueError
    except: row['_status'],row['_error']='error','Qty must be positive';return

def validate_opening_balance_row(row):
    if not row.get('Type','').strip() or row.get('Type').strip().lower() not in ['ar','ap','inventory','bank']:
        row['_status'],row['_error']='error','Type must be: AR, AP, Inventory, or Bank';return
    try:
        if float(row.get('Amount','0').strip())<=0: raise ValueError
    except: row['_status'],row['_error']='error','Amount must be positive';return

# ========== IMPORT FUNCTION ==========

def import_row(module, row):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    user_id = session['user_id']
    
    if module == 'cash':
        desc = row['Description'].strip()
        amt = float(row['Amount'].strip())
        tx_type = row['Type'].strip().lower()
        cat = row.get('Category', '').strip() or 'General'
        tx_date = row['Date'].strip()
        cursor.execute(
            "INSERT INTO transactions (user_id, description, amount, type, category, transaction_date) VALUES (%s,%s,%s,%s,%s,%s)",
            (user_id, desc, amt, tx_type, cat, tx_date))
        tx_id = cursor.lastrowid
        if session.get('plan') in ['professional', 'suite']:
            _create_journal_for_cash(cursor, user_id, tx_date, desc, amt, tx_type, cat, tx_id)
    
    elif module == 'sales':
        cust = row['Customer'].strip()
        amt = float(row['Amount'].strip())
        sale_date = row['Date'].strip()
        desc = row.get('Description', '').strip()
        cursor.execute(
            "INSERT INTO sales (user_id, customer_name, amount, sale_date, description) VALUES (%s,%s,%s,%s,%s)",
            (user_id, cust, amt, sale_date, desc))
        sale_id = cursor.lastrowid
        if session.get('plan') in ['professional', 'suite']:
            _create_journal_for_sale(cursor, user_id, sale_date, cust, desc, amt, sale_id)
    
    elif module == 'inventory':
        cursor.execute(
            "INSERT INTO products (user_id, name, description, quantity, price, cogs, category, reorder_level) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (user_id, row['Name'].strip(), row.get('Description','').strip(),
             int(row.get('Quantity','0').strip()), float(row.get('Price','0').strip()),
             float(row.get('Cost','0').strip() or 0), row.get('Category','').strip() or 'General',
             int(row.get('Reorder Level','5').strip() or 5)))
    
    elif module == 'customers':
        cursor.execute("INSERT INTO customers (user_id, name, email, phone) VALUES (%s,%s,%s,%s)",
            (user_id, row['Name'].strip(), row.get('Email','').strip(), row.get('Phone','').strip()))
    
    elif module == 'suppliers':
        cursor.execute("INSERT INTO suppliers (user_id, name, email, phone, address) VALUES (%s,%s,%s,%s,%s)",
            (user_id, row['Name'].strip(), row.get('Email','').strip(), row.get('Phone','').strip(), row.get('Address','').strip()))
    
    elif module == 'bills':
        cursor.execute("SELECT id FROM suppliers WHERE name = %s AND user_id = %s", (row['Supplier'].strip(), user_id))
        sup = cursor.fetchone()
        supplier_id = sup['id'] if sup else None
        bill_number = f"BILL-{date.today().strftime('%Y%m%d')}-{user_id}"
        amt = float(row['Amount'].strip())
        due = row['Due_Date'].strip()
        desc = row.get('Description','').strip()
        cursor.execute(
            "INSERT INTO bills (user_id, supplier_id, bill_number, amount, due_date, description, status) VALUES (%s,%s,%s,%s,%s,%s,'unpaid')",
            (user_id, supplier_id, bill_number, amt, due, desc))
        if session.get('plan') in ['professional', 'suite'] and supplier_id:
            _create_journal_for_bill(cursor, user_id, due, desc, amt, supplier_id, bill_number)
    
    elif module == 'invoices':
        cursor.execute("SELECT id FROM customers WHERE name = %s AND user_id = %s", (row['Customer'].strip(), user_id))
        cust = cursor.fetchone()
        customer_id = cust['id'] if cust else None
        invoice_number = f"INV-{date.today().strftime('%Y%m%d')}-{user_id}"
        amt = float(row['Amount'].strip())
        due = row['Due_Date'].strip()
        desc = row.get('Description','').strip()
        cursor.execute(
            "INSERT INTO invoices (user_id, customer_id, invoice_number, amount, due_date, description, status) VALUES (%s,%s,%s,%s,%s,%s,'unpaid')",
            (user_id, customer_id, invoice_number, amt, due, desc))
        if session.get('plan') in ['professional', 'suite'] and customer_id:
            _create_journal_for_invoice(cursor, user_id, due, desc, amt, customer_id, invoice_number)
    
    elif module == 'po':
        _import_po(cursor, user_id, row)
    
    elif module == 'so':
        _import_so(cursor, user_id, row)
    
    elif module == 'opening_balances':
        bal_type = row['Type'].strip().lower()
        ref_name = row.get('Name', row.get('Reference', 'Opening Balance')).strip()
        amt = float(row['Amount'].strip())
        entry_date = row.get('Date', date.today().isoformat()).strip()
        cursor.execute(
            "INSERT INTO opening_balances (user_id, balance_type, reference_name, amount, entry_date) VALUES (%s,%s,%s,%s,%s)",
            (user_id, bal_type, ref_name, amt, entry_date))
        if session.get('plan') in ['professional', 'suite']:
            _create_journal_for_opening_balance(cursor, user_id, entry_date, bal_type, ref_name, amt)
    
    db.commit()
    cursor.close()
    db.close()

# ========== JOURNAL CREATION HELPERS ==========

def _create_journal_for_cash(cursor, user_id, tx_date, description, amount, tx_type, category, tx_id):
    cursor.execute("""
        SELECT debit_account_id, credit_account_id FROM transaction_account_mapping
        WHERE transaction_type = %s AND (category = %s OR category IS NULL)
        ORDER BY category IS NULL LIMIT 1
    """, (tx_type, category))
    mapping = cursor.fetchone()
    if not mapping: return
    cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description, reference) VALUES (%s,%s,%s,%s)",
        (user_id, tx_date, description, f"IMP-{tx_id}"))
    entry_id = cursor.lastrowid
    if tx_type == 'income':
        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,%s,0)", (entry_id, mapping['debit_account_id'], amount))
        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,0,%s)", (entry_id, mapping['credit_account_id'], amount))
    else:
        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,%s,0)", (entry_id, mapping['debit_account_id'], amount))
        cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,0,%s)", (entry_id, mapping['credit_account_id'], amount))

def _create_journal_for_sale(cursor, user_id, sale_date, customer_name, description, amount, sale_id):    
    cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '1000'")
    cash_acct = cursor.fetchone()
    cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '4000'")
    revenue_acct = cursor.fetchone()
    if not cash_acct or not revenue_acct: return
    cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description, reference) VALUES (%s,%s,%s,%s)",
        (user_id, sale_date, f"Sale to {customer_name} - {description or 'Imported'}", f"IMP-S-{sale_id}"))
    entry_id = cursor.lastrowid
    cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,%s,0)", (entry_id, cash_acct['id'], amount))
    cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,0,%s)", (entry_id, revenue_acct['id'], amount))

def _create_journal_for_bill(cursor, user_id, due_date, description, amount, supplier_id, bill_number):
    cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '2000'")
    ap_acct = cursor.fetchone()
    cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '5300'")
    exp_acct = cursor.fetchone()
    if not ap_acct or not exp_acct: return
    cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description, reference) VALUES (%s,%s,%s,%s)",
        (user_id, due_date, f"Bill #{bill_number} - {description or 'Imported'}", f"IMP-B-{bill_number}"))
    entry_id = cursor.lastrowid
    cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,%s,0)", (entry_id, exp_acct['id'], amount))
    cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,0,%s)", (entry_id, ap_acct['id'], amount))

def _create_journal_for_invoice(cursor, user_id, due_date, description, amount, customer_id, invoice_number):
    cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '1100'")
    ar_acct = cursor.fetchone()
    cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '4000'")
    rev_acct = cursor.fetchone()
    if not ar_acct or not rev_acct: return
    cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description, reference) VALUES (%s,%s,%s,%s)",
        (user_id, due_date, f"Invoice #{invoice_number} - {description or 'Imported'}", f"IMP-I-{invoice_number}"))
    entry_id = cursor.lastrowid
    cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,%s,0)", (entry_id, ar_acct['id'], amount))
    cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,0,%s)", (entry_id, rev_acct['id'], amount))

def _create_journal_for_opening_balance(cursor, user_id, entry_date, bal_type, ref_name, amount):
    if bal_type == 'ar':
        cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '1100'")
        ar = cursor.fetchone()
        cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '3000'")
        equity = cursor.fetchone()
        if ar and equity:
            cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description) VALUES (%s,%s,%s)",
                (user_id, entry_date, f"Opening AR Balance - {ref_name}"))
            eid = cursor.lastrowid
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,%s,0)", (eid, ar['id'], amount))
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,0,%s)", (eid, equity['id'], amount))
    elif bal_type == 'ap':
        cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '2000'")
        ap = cursor.fetchone()
        cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '3000'")
        equity = cursor.fetchone()
        if ap and equity:
            cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description) VALUES (%s,%s,%s)",
                (user_id, entry_date, f"Opening AP Balance - {ref_name}"))
            eid = cursor.lastrowid
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,%s,0)", (eid, equity['id'], amount))
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,0,%s)", (eid, ap['id'], amount))
    elif bal_type == 'inventory':
        cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '1200'")
        inv = cursor.fetchone()
        cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '3000'")
        equity = cursor.fetchone()
        if inv and equity:
            cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description) VALUES (%s,%s,%s)",
                (user_id, entry_date, f"Opening Inventory Balance - {ref_name}"))
            eid = cursor.lastrowid
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,%s,0)", (eid, inv['id'], amount))
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,0,%s)", (eid, equity['id'], amount))
    elif bal_type == 'bank':
        cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '1000'")
        cash = cursor.fetchone()
        cursor.execute("SELECT id FROM chart_of_accounts WHERE code = '3000'")
        equity = cursor.fetchone()
        if cash and equity:
            cursor.execute("INSERT INTO journal_entries (user_id, entry_date, description) VALUES (%s,%s,%s)",
                (user_id, entry_date, f"Opening Bank Balance - {ref_name}"))
            eid = cursor.lastrowid
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,%s,0)", (eid, cash['id'], amount))
            cursor.execute("INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (%s,%s,0,%s)", (eid, equity['id'], amount))

def _import_po(cursor, user_id, row):
    supplier_name = row['Supplier'].strip()
    cursor.execute("SELECT id FROM suppliers WHERE name = %s AND user_id = %s", (supplier_name, user_id))
    sup = cursor.fetchone()
    supplier_id = sup['id'] if sup else None
    po_number = f"PO-{date.today().strftime('%Y%m%d')}-{user_id}"
    order_date = row.get('Order_Date', date.today().isoformat()).strip()
    expected_date = row.get('Expected_Date', '').strip()
    
    cursor.execute("SELECT id FROM purchase_orders WHERE po_number = %s AND user_id = %s", (po_number, user_id))
    existing = cursor.fetchone()
    if existing:
        po_id = existing['id']
    else:
        cursor.execute(
            "INSERT INTO purchase_orders (user_id, supplier_id, po_number, order_date, expected_date, total_amount, status) VALUES (%s,%s,%s,%s,%s,0,'ordered')",
            (user_id, supplier_id, po_number, order_date, expected_date if expected_date else None))
        po_id = cursor.lastrowid
    
    item_name = row['Item'].strip()
    qty = int(row.get('Qty', '1').strip())
    price = float(row.get('Unit_Price', '0').strip())
    cursor.execute(
        "INSERT INTO po_items (po_id, product_name, quantity, unit_price) VALUES (%s,%s,%s,%s)",
        (po_id, item_name, qty, price))
    cursor.execute("UPDATE purchase_orders SET total_amount = total_amount + %s WHERE id = %s", (qty * price, po_id))

def _import_so(cursor, user_id, row):
    customer_name = row['Customer'].strip()
    cursor.execute("SELECT id FROM customers WHERE name = %s AND user_id = %s", (customer_name, user_id))
    cust = cursor.fetchone()
    customer_id = cust['id'] if cust else None
    so_number = f"SO-{date.today().strftime('%Y%m%d')}-{user_id}"
    order_date = row.get('Order_Date', date.today().isoformat()).strip()
    delivery_date = row.get('Delivery_Date', '').strip()
    
    cursor.execute("SELECT id FROM sales_orders WHERE so_number = %s AND user_id = %s", (so_number, user_id))
    existing = cursor.fetchone()
    if existing:
        so_id = existing['id']
    else:
        cursor.execute(
            "INSERT INTO sales_orders (user_id, customer_id, so_number, order_date, delivery_date, total_amount, status) VALUES (%s,%s,%s,%s,%s,0,'confirmed')",
            (user_id, customer_id, so_number, order_date, delivery_date if delivery_date else None))
        so_id = cursor.lastrowid
    
    item_name = row['Item'].strip()
    qty = int(row.get('Qty', '1').strip())
    price = float(row.get('Unit_Price', '0').strip())
    cursor.execute(
        "INSERT INTO so_items (so_id, product_name, quantity, unit_price) VALUES (%s,%s,%s,%s)",
        (so_id, item_name, qty, price))
    cursor.execute("UPDATE sales_orders SET total_amount = total_amount + %s WHERE id = %s", (qty * price, so_id))