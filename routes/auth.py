from flask import Blueprint, render_template, request, redirect, session, url_for, jsonify
import hashlib
from datetime import date, datetime, timedelta
import random
import string
from models.database import get_db
from routes.permissions import create_enterprise_role_templates

auth_bp = Blueprint('auth', __name__)

# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def generate_business_id():
    """Generate a unique Business ID like TARA-X7K9-2M4P."""
    chars = string.ascii_uppercase + string.digits
    return f"TARA-{''.join(random.choices(chars, k=4))}-{''.join(random.choices(chars, k=4))}"

def generate_business_password():
    """Generate a random business password for Starter users."""
    return f"tara-{random.randint(1000, 9999)}"

# ──────────────────────────────────────────────
# REGISTRATION
# ──────────────────────────────────────────────

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    plan_slug = request.args.get('plan', 'starter')
    
    # Validate plan
    valid_plans = ['starter', 'essentials', 'professional', 'suite']
    if plan_slug not in valid_plans:
        plan_slug = 'starter'
    
    if request.method == 'POST':
        return handle_registration(plan_slug)
    
    # GET — show appropriate registration form
    if plan_slug == 'starter':
        return render_template('register_starter.html', plan='starter')
    else:
        return render_template('register_paid.html', plan=plan_slug)


def handle_registration(plan_slug):
    """Process registration form submission."""
    full_name = request.form.get('full_name', '').strip()
    username = request.form.get('username', '').strip().lower()
    password = request.form.get('password', '')
    business_name = request.form.get('business_name', '').strip()
    industry = request.form.get('industry', '').strip()
    business_size = request.form.get('business_size', 'solo')
    email = request.form.get('email', '').strip()
    
    # Validation
    if not full_name or not username or not password or not business_name:
        return render_template(
            'register_starter.html' if plan_slug == 'starter' else 'register_paid.html',
            plan=plan_slug,
            error='Please fill in all required fields.'
        )
    
    if len(password) < 6:
        return render_template(
            'register_starter.html' if plan_slug == 'starter' else 'register_paid.html',
            plan=plan_slug,
            error='Password must be at least 6 characters.'
        )
    
    # Plan mapping
    plan_map = {'solo': 1, 'small': 2, 'growing': 3, 'medium': 4}
    plan_id = plan_map.get(business_size, 1)
    
    # If coming from Starter registration, force plan_id=1
    if plan_slug == 'starter':
        plan_id = 1
        business_size = 'solo'
    
    plan_slug_map = {1: 'starter', 2: 'essentials', 3: 'professional', 4: 'suite'}
    plan_name_map = {1: 'Starter', 2: 'Essentials', 3: 'Professional', 4: 'Suite'}
    
    # Business password
    business_password = request.form.get('business_password', '')
    if plan_slug == 'starter':
        business_password = generate_business_password()
    elif not business_password or len(business_password) < 4:
        return render_template('register_paid.html', plan=plan_slug,
                              error='Business password must be at least 4 characters.')
    
    # VAT
    vat_registered = 0 if business_size == 'solo' else 1
    
    # Trial end date (14 days for paid plans)
    trial_ends_at = None
    billing_cycle = 'monthly'
    if plan_slug != 'starter':
        trial_ends_at = date.today() + timedelta(days=14)
        billing_cycle = request.form.get('billing_cycle', 'monthly')
    
    # Hash passwords
    hashed_password = hashlib.sha256(password.encode()).hexdigest()
    hashed_business_password = hashlib.sha256(business_password.encode()).hexdigest()
    
    # Generate unique Business ID
    business_id = generate_business_id()
    db = get_db()
    cursor = db.cursor()
    
    # Ensure uniqueness
    attempts = 0
    while attempts < 10:
        cursor.execute("SELECT id FROM users WHERE business_id = %s", (business_id,))
        if not cursor.fetchone():
            break
        business_id = generate_business_id()
        attempts += 1
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            INSERT INTO users (username, password, role, full_name, email, industry, 
                             business_size, plan_id, business_id, business_password, 
                             business_name, vat_registered, trial_ends_at, billing_cycle)
            VALUES (%s, %s, 'admin', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (username, hashed_password, full_name, email, industry, business_size,
              plan_id, business_id, hashed_business_password, business_name,
              vat_registered, trial_ends_at, billing_cycle))
        db.commit()
        
        # Fetch the created user
        cursor.execute("SELECT * FROM users WHERE username = %s AND business_id = %s",
                       (username, business_id))
        user = cursor.fetchone()
        
        # Set session
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        session['business_id'] = user['business_id']
        session['business_name'] = user['business_name']
        session['vat_registered'] = bool(user.get('vat_registered', 0))
        session['plan'] = plan_slug_map.get(plan_id, 'starter')
        session['plan_name'] = plan_name_map.get(plan_id, 'Starter')
        session['trial_ends_at'] = str(trial_ends_at) if trial_ends_at else None
        
        # Enterprise role templates for Suite
        if plan_id == 4:
            create_enterprise_role_templates(business_id, user['id'])
        
        # Process add-on selections (paid plans only)
        selected_addons = []
        if plan_slug != 'starter':
            addon_ids = request.form.getlist('addons')
            if addon_ids:
                addon_cursor = db.cursor()
                for addon_id in addon_ids:
                    addon_cursor.execute("""
                        INSERT INTO user_addons (user_id, addon_id, status, trial_ends_at)
                        VALUES (%s, %s, 'trial', %s)
                    """, (user['id'], addon_id, trial_ends_at))
                    selected_addons.append(addon_id)
                db.commit()
                addon_cursor.close()
        
        cursor.close()
        db.close()
        
        # Render success page
        return render_template('registration_success.html',
                              business_id=business_id,
                              business_name=business_name,
                              business_password=business_password,
                              username=username,
                              plan=plan_name_map.get(plan_id, 'Starter'),
                              plan_slug=plan_slug_map.get(plan_id, 'starter'),
                              is_trial=plan_slug != 'starter',
                              trial_ends_at=trial_ends_at,
                              selected_addons=selected_addons)
    
    except Exception as e:
        db.rollback()
        cursor.close()
        db.close()
        return render_template(
            'register_starter.html' if plan_slug == 'starter' else 'register_paid.html',
            plan=plan_slug,
            error=f'Registration failed. Please try again. {str(e)}'
        )


# ──────────────────────────────────────────────
# LOGIN (unchanged from current working version)
# ──────────────────────────────────────────────

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
            
            plan_id = user.get('plan_id', 1)
            cursor.execute("SELECT slug, name FROM plans WHERE id = %s", (plan_id,))
            plan = cursor.fetchone()
            
            session['plan'] = plan['slug'] if plan else 'starter'
            session['plan_name'] = plan['name'] if plan else 'Starter'
            session['vat_registered'] = bool(user.get('vat_registered', 0))
            session['trial_ends_at'] = str(user.get('trial_ends_at')) if user.get('trial_ends_at') else None

            cursor.close()
            db.close()
            
            if session['plan'] == 'starter':
                return redirect(url_for('quick_tap.index'))
            return redirect(url_for('dashboard.dashboard'))
        
        cursor.close()
        db.close()
        return render_template('login.html', error='Invalid credentials.')
    
    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))