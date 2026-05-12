from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from models.database import get_db
from datetime import datetime

tasks_bp = Blueprint('tasks', __name__)

@tasks_bp.route('/tasks')
def task_list():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('plan') not in ['professional', 'suite']:
        return redirect(url_for('dashboard.dashboard'))
    
    user_id = session['user_id']
    business_id = session.get('business_id')
    role = session.get('role')
    status_filter = request.args.get('status', 'open')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    if role in ['admin', 'owner']:
        cursor.execute("""
            SELECT mn.*, 
                   creator.username as created_by_name,
                   assignee.username as assigned_to_name
            FROM module_notes mn
            JOIN users creator ON mn.created_by = creator.id
            LEFT JOIN users assignee ON mn.assigned_to = assignee.id
            WHERE mn.business_id = %s
            ORDER BY FIELD(mn.status, 'open', 'in_progress', 'done'), 
                     FIELD(mn.priority, 'urgent', 'normal'),
                     mn.created_at DESC
        """, (business_id,))
    else:
        cursor.execute("""
            SELECT mn.*, 
                   creator.username as created_by_name,
                   assignee.username as assigned_to_name
            FROM module_notes mn
            JOIN users creator ON mn.created_by = creator.id
            LEFT JOIN users assignee ON mn.assigned_to = assignee.id
            WHERE mn.business_id = %s 
              AND (mn.assigned_to = %s OR mn.created_by = %s)
            ORDER BY FIELD(mn.status, 'open', 'in_progress', 'done'), 
                     FIELD(mn.priority, 'urgent', 'normal'),
                     mn.created_at DESC
        """, (business_id, user_id, user_id))
    
    tasks = cursor.fetchall()
    
    # Get team members for assignment dropdown
    cursor.execute("""
        SELECT id, username, role FROM users 
        WHERE business_id = %s AND id != %s
        ORDER BY username
    """, (business_id, user_id))
    team = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('tasks.html', tasks=tasks, team=team, 
                          status_filter=status_filter, role=role)


@tasks_bp.route('/tasks/create', methods=['POST'])
def create_task():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    user_id = session['user_id']
    business_id = session.get('business_id')
    data = request.get_json()
    
    module_type = data.get('module_type')
    record_id = data.get('record_id', 0)
    note_text = data.get('note_text', '').strip()
    assigned_to = data.get('assigned_to')
    priority = data.get('priority', 'normal')
    
    if not note_text:
        return jsonify({'success': False, 'error': 'Enter a note'}), 400
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO module_notes (business_id, module_type, record_id, note_text, 
                                  created_by, assigned_to, priority)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (business_id, module_type, record_id, note_text, user_id, assigned_to, priority))
    db.commit()
    note_id = cursor.lastrowid
    cursor.close()
    db.close()
    
    return jsonify({'success': True, 'id': note_id, 'message': 'Task created'})


@tasks_bp.route('/tasks/<int:note_id>/status', methods=['POST'])
def update_task_status(note_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    user_id = session['user_id']
    data = request.get_json()
    new_status = data.get('status')
    
    if new_status not in ['open', 'in_progress', 'done']:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400
    
    db = get_db()
    cursor = db.cursor()
    
    if new_status == 'done':
        cursor.execute("""
            UPDATE module_notes 
            SET status = 'done', resolved_by = %s, resolved_at = NOW()
            WHERE id = %s
        """, (user_id, note_id))
    else:
        cursor.execute("""
            UPDATE module_notes SET status = %s WHERE id = %s
        """, (new_status, note_id))
    
    db.commit()
    cursor.close()
    db.close()
    
    return jsonify({'success': True, 'message': 'Status updated'})


@tasks_bp.route('/api/tasks/count')
def task_count():
    if 'user_id' not in session:
        return jsonify({'count': 0})
    
    user_id = session['user_id']
    business_id = session.get('business_id')
    role = session.get('role')
    
    db = get_db()
    cursor = db.cursor()
    
    if role in ['admin', 'owner']:
        cursor.execute("""
            SELECT COUNT(*) FROM module_notes 
            WHERE business_id = %s AND status != 'done'
        """, (business_id,))
    else:
        cursor.execute("""
            SELECT COUNT(*) FROM module_notes 
            WHERE business_id = %s AND assigned_to = %s AND status != 'done'
        """, (business_id, user_id))
    
    count = cursor.fetchone()[0]
    cursor.close()
    db.close()
    
    return jsonify({'count': count})

@tasks_bp.route('/tasks/list/<module_type>/<int:record_id>')
def list_notes(module_type, record_id):
    if 'user_id' not in session:
        return jsonify({'notes': []})
    
    business_id = session.get('business_id')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT mn.*, 
               creator.username as created_by_name,
               assignee.username as assigned_to_name,
               DATE_FORMAT(mn.created_at, '%b %d, %I:%M %p') as created_at
        FROM module_notes mn
        JOIN users creator ON mn.created_by = creator.id
        LEFT JOIN users assignee ON mn.assigned_to = assignee.id
        WHERE mn.business_id = %s 
          AND mn.module_type = %s 
          AND mn.record_id = %s
        ORDER BY mn.created_at DESC
    """, (business_id, module_type, record_id))
    notes = cursor.fetchall()
    cursor.close()
    db.close()
    
    return jsonify({'notes': notes})

@tasks_bp.route('/tasks/team')
def team_list():
    if 'user_id' not in session:
        return jsonify({'team': []})
    
    business_id = session.get('business_id')
    user_id = session['user_id']
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, username, role FROM users 
        WHERE business_id = %s AND id != %s
        ORDER BY username
    """, (business_id, user_id))
    team = cursor.fetchall()
    cursor.close()
    db.close()
    
    return jsonify({'team': team})