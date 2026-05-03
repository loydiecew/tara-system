from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date
import csv
import io
from models.database import get_db

import_bp = Blueprint('import_data', __name__)

ALLOWED_MODULES = ['cash', 'sales', 'inventory', 'customers', 'suppliers', 'bills', 'invoices']

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


def import_row(module, row):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if module == 'cash':
        cursor.execute("INSERT INTO transactions (user_id, description, amount, type, category, transaction_date) VALUES (%s,%s,%s,%s,%s,%s)",
            (session['user_id'], row['Description'].strip(), float(row['Amount'].strip()), row['Type'].strip().lower(), row.get('Category','').strip() or 'General', row['Date'].strip()))
    elif module == 'sales':
        cursor.execute("INSERT INTO sales (user_id, customer_name, amount, sale_date, description) VALUES (%s,%s,%s,%s,%s)",
            (session['user_id'], row['Customer'].strip(), float(row['Amount'].strip()), row['Date'].strip(), row.get('Description','').strip()))
    elif module == 'inventory':
        cursor.execute("INSERT INTO products (user_id, name, description, quantity, price, cogs, category, reorder_level) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (session['user_id'], row['Name'].strip(), row.get('Description','').strip(), int(row.get('Quantity','0').strip()), float(row.get('Price','0').strip()), float(row.get('Cost','0').strip() or 0), row.get('Category','').strip() or 'General', int(row.get('Reorder Level','5').strip() or 5)))
    elif module == 'customers':
        cursor.execute("INSERT INTO customers (user_id, name, email, phone) VALUES (%s,%s,%s,%s)",
            (session['user_id'], row['Name'].strip(), row.get('Email','').strip(), row.get('Phone','').strip()))
    elif module == 'suppliers':
        cursor.execute("INSERT INTO suppliers (user_id, name, email, phone, address) VALUES (%s,%s,%s,%s,%s)",
            (session['user_id'], row['Name'].strip(), row.get('Email','').strip(), row.get('Phone','').strip(), row.get('Address','').strip()))
    elif module == 'bills':
        # Find supplier by name
        cursor.execute("SELECT id FROM suppliers WHERE name = %s AND user_id = %s", (row['Supplier'].strip(), session['user_id']))
        sup = cursor.fetchone()
        supplier_id = sup['id'] if sup else None
        cursor.execute("INSERT INTO bills (user_id, supplier_id, amount, due_date, description, status) VALUES (%s,%s,%s,%s,%s,'unpaid')",
            (session['user_id'], supplier_id, float(row['Amount'].strip()), row['Due_Date'].strip(), row.get('Description','').strip()))
    elif module == 'invoices':
        # Find customer by name
        cursor.execute("SELECT id FROM customers WHERE name = %s AND user_id = %s", (row['Customer'].strip(), session['user_id']))
        cust = cursor.fetchone()
        customer_id = cust['id'] if cust else None
        cursor.execute("INSERT INTO invoices (user_id, customer_id, amount, due_date, description, status) VALUES (%s,%s,%s,%s,%s,'unpaid')",
            (session['user_id'], customer_id, float(row['Amount'].strip()), row['Due_Date'].strip(), row.get('Description','').strip()))
    
    db.commit()
    cursor.close()
    db.close()