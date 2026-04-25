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