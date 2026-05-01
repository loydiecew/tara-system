from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date
import csv
import io
from models.database import get_db

import_bp = Blueprint('import_data', __name__)

ALLOWED_MODULES = ['cash', 'sales', 'inventory', 'customers', 'suppliers']

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
    errors = []
    active_tab = request.args.get('tab', 'cash')
    
    if request.method == 'POST':
        active_tab = request.form.get('module', 'cash')
        
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
        
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        reader = csv.DictReader(stream)
        
        confirm = request.form.get('confirm') == 'true'
        
        for row_num, row in enumerate(reader, start=2):
            row['_row'] = row_num
            row['_status'] = 'valid'
            row['_error'] = ''
            
            # Validate based on module
            if active_tab == 'cash':
                validate_cash_row(row)
            elif active_tab == 'sales':
                validate_sales_row(row)
            elif active_tab == 'inventory':
                validate_inventory_row(row)
            elif active_tab == 'customers':
                validate_customer_row(row)
            elif active_tab == 'suppliers':
                validate_supplier_row(row)
            
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
        
        if confirm and imported > 0:
            flash(f'{imported} records imported successfully! {skipped} skipped.', 'success')
            return redirect(url_for('import_data.import_data', tab=active_tab))
        
        # If POST but not confirmed, return only the preview HTML fragment (AJAX request)
        return render_template('import_preview.html',
                             preview=preview,
                             active_tab=active_tab,
                             imported=imported,
                             skipped=skipped)
    
    # GET request — render the full page
    return render_template('import_data.html',
                         username=session['username'],
                         active_tab=active_tab)
                         
def validate_cash_row(row):
    """Validate cash transaction row"""
    if not row.get('Date', '').strip():
        row['_status'] = 'error'
        row['_error'] = 'Date is required'
        return
    try:
        date.fromisoformat(row['Date'].strip())
    except:
        row['_status'] = 'error'
        row['_error'] = 'Invalid date format (use YYYY-MM-DD)'
        return
    
    if not row.get('Description', '').strip():
        row['_status'] = 'error'
        row['_error'] = 'Description is required'
        return
    
    try:
        amount = float(row.get('Amount', '0').strip())
        if amount <= 0:
            raise ValueError
    except:
        row['_status'] = 'error'
        row['_error'] = 'Amount must be a positive number'
        return
    
    trans_type = row.get('Type', '').strip().lower()
    if trans_type not in ['income', 'expense']:
        row['_status'] = 'error'
        row['_error'] = 'Type must be "income" or "expense"'
        return


def validate_sales_row(row):
    """Validate sales row"""
    if not row.get('Date', '').strip():
        row['_status'] = 'error'
        row['_error'] = 'Date is required'
        return
    try:
        date.fromisoformat(row['Date'].strip())
    except:
        row['_status'] = 'error'
        row['_error'] = 'Invalid date format (use YYYY-MM-DD)'
        return
    
    if not row.get('Customer', '').strip():
        row['_status'] = 'error'
        row['_error'] = 'Customer name is required'
        return
    
    try:
        amount = float(row.get('Amount', '0').strip())
        if amount <= 0:
            raise ValueError
    except:
        row['_status'] = 'error'
        row['_error'] = 'Amount must be a positive number'
        return


def validate_inventory_row(row):
    """Validate inventory/product row"""
    if not row.get('Name', '').strip():
        row['_status'] = 'error'
        row['_error'] = 'Product name is required'
        return
    try:
        price = float(row.get('Price', '0').strip())
        if price < 0:
            raise ValueError
    except:
        row['_status'] = 'error'
        row['_error'] = 'Price must be a valid number'
        return
    try:
        qty = int(row.get('Quantity', '0').strip())
        if qty < 0:
            raise ValueError
    except:
        row['_status'] = 'error'
        row['_error'] = 'Quantity must be a whole number'
        return


def validate_customer_row(row):
    """Validate customer row"""
    if not row.get('Name', '').strip():
        row['_status'] = 'error'
        row['_error'] = 'Customer name is required'
        return


def validate_supplier_row(row):
    """Validate supplier row"""
    if not row.get('Name', '').strip():
        row['_status'] = 'error'
        row['_error'] = 'Supplier name is required'
        return


def import_row(module, row):
    """Insert a validated row into the database"""
    db = get_db()
    cursor = db.cursor()
    
    if module == 'cash':
        cursor.execute("""
            INSERT INTO transactions (user_id, description, amount, type, category, transaction_date)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            session['user_id'],
            row['Description'].strip(),
            float(row['Amount'].strip()),
            row['Type'].strip().lower(),
            row.get('Category', '').strip() or 'General',
            row['Date'].strip()
        ))
    elif module == 'sales':
        cursor.execute("""
            INSERT INTO sales (user_id, customer_name, amount, sale_date, description)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            session['user_id'],
            row['Customer'].strip(),
            float(row['Amount'].strip()),
            row['Date'].strip(),
            row.get('Description', '').strip()
        ))
    elif module == 'inventory':
        cursor.execute("""
            INSERT INTO products (user_id, name, description, quantity, price, cogs, category, reorder_level)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            session['user_id'],
            row['Name'].strip(),
            row.get('Description', '').strip(),
            int(row.get('Quantity', '0').strip()),
            float(row.get('Price', '0').strip()),
            float(row.get('Cost', '0').strip() or 0),
            row.get('Category', '').strip() or 'General',
            int(row.get('Reorder Level', '5').strip() or 5)
        ))
    elif module == 'customers':
        cursor.execute("""
            INSERT INTO customers (user_id, name, email, phone)
            VALUES (%s, %s, %s, %s)
        """, (
            session['user_id'],
            row['Name'].strip(),
            row.get('Email', '').strip(),
            row.get('Phone', '').strip()
        ))
    elif module == 'suppliers':
        cursor.execute("""
            INSERT INTO suppliers (user_id, name, email, phone, address)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            session['user_id'],
            row['Name'].strip(),
            row.get('Email', '').strip(),
            row.get('Phone', '').strip(),
            row.get('Address', '').strip()
        ))
    
    db.commit()
    cursor.close()
    db.close()