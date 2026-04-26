from flask import Blueprint, render_template, request, redirect, session, url_for
import hashlib
from models.database import get_db
from models.helpers import get_user_plan

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
        user = cursor.fetchone()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            
            plan_id = user.get('plan_id', 1)
            cursor.execute("SELECT slug, name FROM plans WHERE id = %s", (plan_id,))
            plan = cursor.fetchone()
            
            session['plan'] = plan['slug'] if plan else 'basic'
            session['plan_name'] = plan['name'] if plan else 'Basic'
            
            cursor.close()
            db.close()
            return redirect(url_for('dashboard.dashboard'))
        
        cursor.close()
        db.close()
        return render_template('login.html', error='Invalid credentials')
    
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        full_name = request.form['full_name']
        industry = request.form['industry']
        business_size = request.form['business_size']
        
        # Map business size to plan_id
        plan_map = {
            'solo': 1,      # Basic
            'small': 2,     # Pro
            'medium': 3     # Enterprise
        }
        plan_id = plan_map.get(business_size, 1)
        
        hashed = hashlib.sha256(password.encode()).hexdigest()
        
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        try:
            cursor.execute("""
                INSERT INTO users (username, password, role, full_name, industry, business_size, plan_id)
                VALUES (%s, %s, 'admin', %s, %s, %s, %s)
            """, (username, hashed, full_name, industry, business_size, plan_id))
            db.commit()
            
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['business_size'] = business_size
            
            # Set plan in session based on business_size
            if business_size == 'solo':
                session['plan'] = 'basic'
                session['plan_name'] = 'Basic'
            elif business_size == 'small':
                session['plan'] = 'pro'
                session['plan_name'] = 'Pro'
            else:
                session['plan'] = 'enterprise'
                session['plan_name'] = 'Enterprise'
            
            cursor.close()
            db.close()
            return redirect(url_for('dashboard.dashboard'))
            
        except Exception as e:
            db.rollback()
            cursor.close()
            db.close()
            return render_template('register.html', error=f"Username already exists: {e}")
    
    return render_template('register.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))