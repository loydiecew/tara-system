from flask import Blueprint, request, session, redirect, url_for, jsonify
from datetime import date
from models.database import get_db

api_bp = Blueprint('api', __name__)

@api_bp.route('/api/categories')
def api_categories():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    trans_type = request.args.get('type', 'income')
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT industry FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    industry = user['industry'] if user else 'retail'
    
    cursor.execute("""
        SELECT name, type FROM categories 
        WHERE (user_id IS NULL OR user_id = %s) 
        AND type = %s
        AND (industry IS NULL OR industry = %s OR industry = 'all')
        ORDER BY name
    """, (session['user_id'], trans_type, industry))
    
    categories = cursor.fetchall()
    cursor.close()
    db.close()
    
    result = {trans_type: categories}
    return jsonify(result)


@api_bp.route('/api/suggest_category', methods=['POST'])
def suggest_category():
    """Suggest a category based on past transaction descriptions."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    description = data.get('description', '').strip().lower()
    
    if not description or len(description) < 2:
        return jsonify({'category': None, 'confidence': 0})
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    business_id = session.get('business_id', session['user_id'])
    
    # Extract keywords (words > 2 chars)
    keywords = [w for w in description.split() if len(w) > 2]
    
    if not keywords:
        cursor.close()
        db.close()
        return jsonify({'category': None, 'confidence': 0})
    
    # Build LIKE conditions for each keyword
    like_clauses = ' OR '.join(['t.description LIKE %s' for _ in keywords])
    params = tuple(['%' + kw + '%' for kw in keywords])
    
    cursor.execute(f"""
        SELECT t.category, COUNT(*) as count
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        WHERE u.business_id = %s 
        AND t.type = 'expense'
        AND ({like_clauses})
        AND t.category IS NOT NULL
        AND t.category != ''
        AND t.deleted_at IS NULL
        GROUP BY t.category
        ORDER BY count DESC
        LIMIT 1
    """, (business_id,) + params)
    
    result = cursor.fetchone()
    cursor.close()
    db.close()
    
    if result and result['count'] > 0:
        # Calculate confidence based on match count vs total
        confidence = min(result['count'] / 10, 1.0)  # Cap at 1.0
        return jsonify({
            'category': result['category'],
            'confidence': round(confidence, 2),
            'matches': result['count']
        })
    
    return jsonify({'category': None, 'confidence': 0})


@api_bp.route('/api/sync_offline', methods=['POST'])
def sync_offline():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    offline_transactions = data.get('transactions', [])
    
    db = get_db()
    cursor = db.cursor()
    saved_count = 0
    
    for tx in offline_transactions:
        try:
            cursor.execute("""
                INSERT INTO transactions (user_id, description, amount, type, category, transaction_date)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                session['user_id'],
                tx.get('description'),
                float(tx.get('amount', 0)),
                tx.get('type', 'expense'),
                tx.get('category', ''),
                tx.get('date', date.today())
            ))
            saved_count += 1
        except Exception as e:
            print(f"Error saving offline transaction: {e}")
    
    db.commit()
    cursor.close()
    db.close()
    
    return jsonify({'synced': saved_count, 'total': len(offline_transactions)})

@api_bp.route('/api/parse_voice', methods=['POST'])
def parse_voice():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.get_json()
    text = data.get('text', '').lower()
    
    result = {
        'description': '',
        'amount': None,
        'type': 'expense',
        'category': ''
    }
    
    if 'income' in text or 'sale' in text or 'received' in text or 'payment' in text:
        result['type'] = 'income'
    elif 'expense' in text or 'spent' in text or 'paid' in text or 'bought' in text:
        result['type'] = 'expense'
    
    import re
    numbers = re.findall(r'(\d+(?:\.\d+)?)', text)
    if numbers:
        result['amount'] = float(numbers[0])
    
    description = text
    if result['amount']:
        description = description.replace(str(int(result['amount'])), '')
    for word in ['income', 'expense', 'sale', 'spent', 'paid', 'received', 'bought', 'for', 'on']:
        description = description.replace(word, '')
    result['description'] = description.strip().capitalize()
    
    if 'rent' in text:
        result['category'] = 'Rent'
    elif 'food' in text or 'supplies' in text or 'ingredients' in text:
        result['category'] = 'Supplies'
    elif 'salary' in text or 'wage' in text or 'staff' in text:
        result['category'] = 'Salaries'
    elif 'electric' in text or 'water' in text or 'utility' in text:
        result['category'] = 'Utilities'
    
    return jsonify(result)

