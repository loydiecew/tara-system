from flask import Blueprint, render_template, request, redirect, session, url_for
import hashlib
from datetime import datetime
import random
import string
from models.database import get_db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        business_id = request.form['business_id']
        business_password = request.form['business_password']
        
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        hashed_business_password = hashlib.sha256(business_password.encode()).hexdigest()
        
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT * FROM users 
            WHERE username = %s AND business_id = %s 
            AND business_password = %s
        """, (username, business_id, hashed_business_password))
        user = cursor.fetchone()
        
        if user and user['password'] == hashed_password:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['business_id'] = user['business_id']
            session['custom_role_id'] = user.get('custom_role_id')
            # Get user's plan
            plan_id = user.get('plan_id', 1)
            cursor.execute("SELECT slug, name FROM plans WHERE id = %s", (plan_id,))
            plan = cursor.fetchone()
            
            session['plan'] = plan['slug'] if plan else 'basic'
            session['plan_name'] = plan['name'] if plan else 'Basic'
            session['vat_registered'] = bool(user.get('vat_registered', 0))

            cursor.close()
            db.close()
            return redirect(url_for('dashboard.dashboard'))
        
        cursor.close()
        db.close()
        return render_template('login.html', error='Invalid credentials. Check username, password, business ID, or business password.')
    
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    plan_slug = request.args.get('plan', 'starter')

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        full_name = request.form['full_name']
        industry = request.form['industry']
        business_size = request.form['business_size']
        business_name = request.form['business_name']
        business_password = request.form['business_password']

        # Map business_size to plan_id
        plan_map = {'solo': 1, 'small': 2, 'growing': 3, 'medium': 4}
        plan_id = plan_map.get(business_size, 1)

        # Plan slugs for session
        plan_slug_map = {1: 'starter', 2: 'essentials', 3: 'professional', 4: 'suite'}
        plan_name_map = {1: 'Starter', 2: 'Essentials', 3: 'Professional', 4: 'Suite'}

        vat_registered = 0 if business_size in ('solo', 'small') else 1

        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        hashed_business_password = hashlib.sha256(business_password.encode()).hexdigest()

        def generate_business_id():
            chars = string.ascii_uppercase + string.digits
            return f"TARA-{''.join(random.choices(chars, k=4))}-{''.join(random.choices(chars, k=4))}"

        business_id = generate_business_id()
        while True:
            db = get_db()
            cursor = db.cursor()
            cursor.execute("SELECT id FROM users WHERE business_id = %s", (business_id,))
            if not cursor.fetchone():
                break
            business_id = generate_business_id()
            cursor.close()
            db.close()

        db = get_db()
        cursor = db.cursor(dictionary=True)

        try:
            cursor.execute("""
                INSERT INTO users (username, password, role, full_name, industry, business_size, plan_id,
                                   business_id, business_password, business_name, vat_registered)
                VALUES (%s, %s, 'admin', %s, %s, %s, %s, %s, %s, %s, %s)
            """, (username, hashed_password, full_name, industry, business_size, plan_id,
                  business_id, hashed_business_password, business_name, vat_registered))
            db.commit()

            cursor.execute("SELECT * FROM users WHERE username = %s AND business_id = %s",
                           (username, business_id))
            user = cursor.fetchone()

            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['business_id'] = user['business_id']
            session['business_name'] = user['business_name']
            session['vat_registered'] = bool(user.get('vat_registered', 0))
            session['plan'] = plan_slug_map.get(plan_id, 'starter')
            session['plan_name'] = plan_name_map.get(plan_id, 'Starter')

            # Suite gets enterprise role templates
            if plan_id == 4:
                from routes.permissions import create_enterprise_role_templates
                create_enterprise_role_templates(business_id, user['id'])

            cursor.close()
            db.close()

            return render_template('registration_success.html',
                                   business_id=business_id,
                                   business_name=business_name,
                                   username=username,
                                   plan=session.get('plan_name', 'Starter'))

        except Exception as e:
            db.rollback()
            cursor.close()
            db.close()
            return render_template('register.html', error=f"Registration failed: {e}", plan=plan_slug)

    return render_template('register.html', plan=plan_slug)

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))