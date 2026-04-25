from models.database import get_db
from datetime import timedelta

def get_user_plan(user_id):
    """Get user's current plan"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.id, p.name, p.slug, p.price_monthly, p.max_users 
        FROM users u
        JOIN plans p ON u.plan_id = p.id
        WHERE u.id = %s
    """, (user_id,))
    plan = cursor.fetchone()
    cursor.close()
    db.close()
    return plan

def user_has_feature(user_id, feature_name):
    """Check if user's plan includes a specific feature"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT COUNT(*) as has_feature
        FROM users u
        JOIN plans p ON u.plan_id = p.id
        JOIN plan_features pf ON p.id = pf.plan_id
        JOIN features f ON pf.feature_id = f.id
        WHERE u.id = %s AND f.name = %s
    """, (user_id, feature_name))
    result = cursor.fetchone()
    cursor.close()
    db.close()
    return result['has_feature'] > 0

def get_user_features(user_id):
    """Get list of features available to user"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT f.name
        FROM users u
        JOIN plans p ON u.plan_id = p.id
        JOIN plan_features pf ON p.id = pf.plan_id
        JOIN features f ON pf.feature_id = f.id
        WHERE u.id = %s
    """, (user_id,))
    features = [row['name'] for row in cursor.fetchall()]
    cursor.close()
    db.close()
    return features

def get_week_range(date_obj):
    """Returns Monday and Sunday of the week containing date_obj"""
    start_of_week = date_obj - timedelta(days=date_obj.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week
