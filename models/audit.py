import json
from flask import request
from models.database import get_db

def log_audit(user_id, username, action, table_name, record_id, old_values=None, new_values=None, ip_address=None):
    """Log all changes to audit_log table"""
    db = get_db()
    cursor = db.cursor()
    
    # Get IP address if not provided
    if ip_address is None and hasattr(request, 'remote_addr'):
        ip_address = request.remote_addr
    
    # Convert old_values and new_values to JSON string
    old_json = json.dumps(old_values, default=str) if old_values else None
    new_json = json.dumps(new_values, default=str) if new_values else None
    
    cursor.execute("""
        INSERT INTO audit_log (user_id, username, action, table_name, record_id, old_values, new_values, ip_address)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (user_id, username, action, table_name, record_id, old_json, new_json, ip_address))
    db.commit()
    cursor.close()
    db.close()
    
    # Also write to business_records for human-readable history
    _write_business_record(user_id, username, action, table_name, record_id, 
                          old_values, new_values, ip_address)


def _write_business_record(user_id, username, action, table_name, record_id, 
                           old_values, new_values, ip_address=None):
    """Write a human-readable entry to business_records"""
    try:
        db2 = get_db()
        cursor2 = db2.cursor()
        
        # Get business_id for this user
        cursor2.execute("SELECT business_id FROM users WHERE id = %s", (user_id,))
        user_row = cursor2.fetchone()
        business_id = user_row[0] if user_row else str(user_id)
        
        # Build human-readable title based on action and module
        module = table_name.rstrip('s') if table_name.endswith('s') else table_name
        
        if action == 'CREATE':
            title = f"Created {module}"
        elif action == 'UPDATE':
            title = f"Updated {module}"
        elif action == 'DELETE':
            title = f"Deleted {module}"
        else:
            title = f"{action} {module}"
        
        # Build description from values
        description = None
        amount = None
        customer_name = None
        
        if new_values:
            if isinstance(new_values, dict):
                description = new_values.get('description', None)
                amount = new_values.get('amount', None)
                customer_name = new_values.get('customer_name', None)
                if not description and 'name' in new_values:
                    description = f"Name: {new_values['name']}"
        
        # Insert into business_records
        cursor2.execute("""
            INSERT INTO business_records 
            (business_id, user_id, user_name, record_type, module, action_title, 
             action_description, amount, reference_type, reference_id, 
             customer_name, old_values, new_values, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            business_id, user_id, username, action.lower(), table_name, title,
            description, amount, table_name, record_id,
            customer_name,
            json.dumps(old_values, default=str) if old_values else None,
            json.dumps(new_values, default=str) if new_values else None,
            ip_address
        ))
        
        db2.commit()
        cursor2.close()
        db2.close()
    except Exception as e:
        # Silently fail — don't break the main operation
        print(f"Business record write failed: {e}")