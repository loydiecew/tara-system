from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from datetime import date
from models.database import get_db
from models.access_control import check_module_access

projects_bp = Blueprint('projects', __name__)

@projects_bp.route('/projects')
def projects():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    if not check_module_access('projects'): return redirect(url_for('dashboard.dashboard'))

    if session.get('plan') not in ['suite']:
        flash('Projects are available on Enterprise plan only.', 'error')
        return redirect(url_for('dashboard.dashboard'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    cursor.execute("""
        SELECT p.*,
            COALESCE((SELECT SUM(t.amount) FROM transactions t WHERE t.project_id = p.id AND t.type = 'income' AND t.deleted_at IS NULL), 0) as total_income,
            COALESCE((SELECT SUM(t.amount) FROM transactions t WHERE t.project_id = p.id AND t.type = 'expense' AND t.deleted_at IS NULL), 0) as total_expense,
            COALESCE((SELECT SUM(s.amount) FROM sales s WHERE s.project_id = p.id), 0) as total_sales
        FROM projects p
        JOIN users u ON p.user_id = u.id
        WHERE u.business_id = %s
        ORDER BY p.status ASC, p.created_at DESC
    """, (business_id,))
    projects = cursor.fetchall()
    
    for p in projects:
        revenue = float(p['total_income'] or 0) + float(p['total_sales'] or 0)
        expense = float(p['total_expense'] or 0)
        p['revenue'] = revenue
        p['expense'] = expense
        p['profit'] = revenue - expense
        p['margin'] = round((p['profit'] / revenue * 100), 1) if revenue > 0 else 0
    
    cursor.close()
    db.close()
    
    return render_template('projects.html',
                         username=session['username'],
                         projects=projects,
                         today=date.today().isoformat())


@projects_bp.route('/add_project', methods=['POST'])
def add_project():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    name = request.form['name']
    client_name = request.form.get('client_name', '')
    description = request.form.get('description', '')
    budget = float(request.form.get('budget', 0))
    start_date = request.form.get('start_date', date.today())
    end_date = request.form.get('end_date', '')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO projects (user_id, name, client_name, description, budget, start_date, end_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (session['user_id'], name, client_name, description, budget, start_date,
          end_date if end_date else None))
    db.commit()
    cursor.close()
    db.close()
    
    flash(f'Project "{name}" created!', 'success')
    return redirect(url_for('projects.projects'))


@projects_bp.route('/update_project/<int:project_id>', methods=['POST'])
def update_project(project_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    status = request.form.get('status', 'active')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE projects SET status = %s WHERE id = %s AND user_id = %s",
                   (status, project_id, session['user_id']))
    db.commit()
    cursor.close()
    db.close()
    
    flash('Project updated.', 'success')
    return redirect(url_for('projects.projects'))


@projects_bp.route('/delete_project/<int:project_id>')
def delete_project(project_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM projects WHERE id = %s AND user_id = %s",
                   (project_id, session['user_id']))
    db.commit()
    cursor.close()
    db.close()
    
    flash('Project deleted.', 'success')
    return redirect(url_for('projects.projects'))