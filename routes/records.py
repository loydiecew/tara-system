from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify
from models.database import get_db
from models.helpers import can_user_access

records_bp = Blueprint('records', __name__)

@records_bp.route('/records')
def records():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('plan') not in ['professional', 'suite']:
        return redirect(url_for('dashboard.dashboard'))
    
    business_id = session.get('business_id', session['user_id'])
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get filter params
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page
    record_type = request.args.get('type', '')
    module_filter = request.args.get('module', '')
    search = request.args.get('search', '')
    
    # Build query
    where = "WHERE business_id = %s"
    params = [business_id]
    
    if record_type:
        where += " AND record_type = %s"
        params.append(record_type)
    if module_filter:
        where += " AND module = %s"
        params.append(module_filter)
    if search:
        where += " AND (action_title LIKE %s OR action_description LIKE %s OR customer_name LIKE %s)"
        like = f"%{search}%"
        params.extend([like, like, like])
    
    cursor.execute(f"SELECT COUNT(*) as total FROM business_records {where}", params)
    total = cursor.fetchone()['total']
    
    cursor.execute(f"""
        SELECT * FROM business_records {where}
        ORDER BY created_at DESC LIMIT %s OFFSET %s
    """, params + [per_page, offset])
    records = cursor.fetchall()
    
    # Get comments count per record
    if records:
        record_ids = [r['id'] for r in records]
        placeholders = ','.join(['%s'] * len(record_ids))
        cursor.execute(f"""
            SELECT record_id, COUNT(*) as comment_count 
            FROM record_comments 
            WHERE record_id IN ({placeholders})
            GROUP BY record_id
        """, record_ids)
        comment_counts = {row['record_id']: row['comment_count'] for row in cursor.fetchall()}
        for r in records:
            r['comment_count'] = comment_counts.get(r['id'], 0)
    
    cursor.close()
    db.close()
    
    return render_template('records.html',
                         username=session['username'],
                         records=records,
                         total=total,
                         page=page,
                         per_page=per_page,
                         record_type=record_type,
                         module_filter=module_filter,
                         search=search)

@records_bp.route('/api/records')
def api_records():
    """API endpoint for dashboard widget"""
    if 'user_id' not in session:
        return jsonify([]), 401
    
    business_id = session.get('business_id', session['user_id'])
    limit = request.args.get('limit', 5, type=int)
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM business_records 
        WHERE business_id = %s 
        ORDER BY created_at DESC LIMIT %s
    """, (business_id, limit))
    records = cursor.fetchall()
    cursor.close()
    db.close()
    
    for r in records:
        if r.get('created_at'):
            r['created_at'] = r['created_at'].isoformat()
    
    return jsonify(records)
