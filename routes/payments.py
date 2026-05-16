from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from datetime import date, datetime
import requests
import base64
import os
from models.database import get_db
from models.email_service import send_email
import qrcode
import io
from flask import Response

payments_bp = Blueprint('payments', __name__)

PAYMONGO_SECRET = os.environ.get('PAYMONGO_SECRET', '')
PAYMONGO_BASE = 'https://api.paymongo.com/v1'

def get_headers():
    credentials = base64.b64encode(f'{PAYMONGO_SECRET}:'.encode()).decode()
    return {
        'Authorization': f'Basic {credentials}',
        'Content-Type': 'application/json'
    }

@payments_bp.route('/create_payment_link/<int:invoice_id>')
def create_payment_link(invoice_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('plan') not in ['essentials', 'professional', 'suite']:
        flash('Payment links are available on Enterprise plan only.', 'error')
        return redirect(url_for('ar.ar'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT i.*, c.name as customer_name, c.email as customer_email
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.id = %s AND i.user_id = %s
    """, (invoice_id, session['user_id']))
    invoice = cursor.fetchone()
    
    if not invoice:
        cursor.close()
        db.close()
        flash('Invoice not found.', 'error')
        return redirect(url_for('ar.ar'))
    
    cursor.execute("SELECT COALESCE(SUM(amount), 0) as total_paid FROM payments WHERE invoice_id = %s", (invoice_id,))
    total_paid = float(cursor.fetchone()['total_paid'])
    remaining = float(invoice['amount']) - total_paid
    
    if remaining <= 0:
        cursor.close()
        db.close()
        flash('Invoice is already fully paid.', 'error')
        return redirect(url_for('ar.ar'))
    
    try:
        response = requests.post(
            f'{PAYMONGO_BASE}/links',
            headers=get_headers(),
            json={
                'data': {
                    'attributes': {
                        'amount': int(remaining * 100),
                        'description': f"Invoice {invoice.get('invoice_number', 'INV-'+str(invoice_id))} - {invoice['customer_name']}",
                        'remarks': f"Payment for invoice from {session.get('business_name', 'TARA')}"
                    }
                }
            }
        )
        
        if response.status_code == 200:
            link_data = response.json()['data']
            checkout_url = link_data['attributes']['checkout_url']
            reference = link_data['id']
            
            cursor.execute("""
                INSERT INTO payment_links (user_id, invoice_id, reference_number, checkout_url, amount)
                VALUES (%s, %s, %s, %s, %s)
            """, (session['user_id'], invoice_id, reference, checkout_url, remaining))
            db.commit()
            cursor.close()
            db.close()
            
            flash(f'Payment link created! <a href="{checkout_url}" target="_blank">Open payment page</a>', 'success')
            return redirect(url_for('ar.ar'))
        else:
            cursor.close()
            db.close()
            flash(f'PayMongo error: {response.text}', 'error')
            return redirect(url_for('ar.ar'))
    except Exception as e:
        cursor.close()
        db.close()
        flash(f'Failed to create payment link: {str(e)}', 'error')
        return redirect(url_for('ar.ar'))


@payments_bp.route('/email_payment_link/<int:invoice_id>')
def email_payment_link(invoice_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    if session.get('plan') not in ['essentials', 'professional', 'suite']:
        flash('Payment links are available on Enterprise plan only.', 'error')
        return redirect(url_for('ar.ar'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT i.*, c.name as customer_name, c.email as customer_email
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.id = %s AND i.user_id = %s
    """, (invoice_id, session['user_id']))
    invoice = cursor.fetchone()
    
    if not invoice or not invoice.get('customer_email'):
        cursor.close()
        db.close()
        flash('Customer has no email address.', 'error')
        return redirect(url_for('ar.ar'))
    
    cursor.execute("SELECT COALESCE(SUM(amount), 0) as total_paid FROM payments WHERE invoice_id = %s", (invoice_id,))
    total_paid = float(cursor.fetchone()['total_paid'])
    remaining = float(invoice['amount']) - total_paid
    
    if remaining <= 0:
        cursor.close()
        db.close()
        flash('Invoice already fully paid.', 'error')
        return redirect(url_for('ar.ar'))
    
    credentials = base64.b64encode(f'{PAYMONGO_SECRET}:'.encode()).decode()
    
    try:
        response = requests.post(
            f'{PAYMONGO_BASE}/links',
            headers={
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/json'
            },
            json={
                'data': {
                    'attributes': {
                        'amount': int(remaining * 100),
                        'description': f"Invoice {invoice.get('invoice_number', 'INV-'+str(invoice_id))}",
                        'remarks': f"Payment for {session.get('business_name', 'TARA')}"
                    }
                }
            }
        )
        
        if response.status_code == 200:
            link_data = response.json()['data']
            checkout_url = link_data['attributes']['checkout_url']
            reference = link_data['id']
            
            cursor.execute("""
                INSERT INTO payment_links (user_id, invoice_id, reference_number, checkout_url, amount)
                VALUES (%s, %s, %s, %s, %s)
            """, (session['user_id'], invoice_id, reference, checkout_url, remaining))
            db.commit()
            
            business_name = session.get('business_name', 'TARA')
            subject = f"Payment Link for Invoice {invoice.get('invoice_number', 'INV-'+str(invoice_id))}"
            html_body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #10b981, #059669); padding: 24px; border-radius: 12px 12px 0 0;">
                    <h2 style="color: white; margin: 0;">{business_name}</h2>
                    <p style="color: rgba(255,255,255,0.8); margin: 4px 0 0;">Invoice Payment</p>
                </div>
                <div style="background: #f8fafc; padding: 24px; border: 1px solid #e2e8f0;">
                    <p>Dear {invoice['customer_name']},</p>
                    <p>Please use the link below to pay your invoice:</p>
                    <div style="background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin: 16px 0;">
                        <p><strong>Invoice:</strong> {invoice.get('invoice_number', 'INV-'+str(invoice_id))}</p>
                        <p><strong>Amount Due:</strong> ₱ {remaining:,.2f}</p>
                    </div>
                    <a href="{checkout_url}" style="background: #10b981; color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; display: inline-block; font-weight: 600; font-size: 16px;">Pay Now</a>
                    <p style="margin-top: 16px; font-size: 12px; color: #94a3b8;">This link is for payment via GCash, Maya, or credit/debit card.</p>
                </div>
            </div>
            """
            
            success, msg = send_email(invoice['customer_email'], subject, html_body)
            cursor.close()
            db.close()
            
            if success:
                flash(f'Payment link sent to {invoice["customer_email"]}!', 'success')
            else:
                flash(f'Payment link created but email failed. Link: {checkout_url}', 'warning')
        else:
            cursor.close()
            db.close()
            flash(f'PayMongo error: {response.text}', 'error')
    except Exception as e:
        cursor.close()
        db.close()
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('ar.ar'))


@payments_bp.route('/payment_success/<int:invoice_id>')
def payment_success(invoice_id):
    return render_template('payment_success.html', invoice_id=invoice_id)




@payments_bp.route('/api/payment_link/<int:invoice_id>')
def api_payment_link(invoice_id):
    """Get the latest payment link for an invoice (JSON)"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT checkout_url, amount, reference_number, created_at
        FROM payment_links
        WHERE invoice_id = %s AND user_id = %s
        ORDER BY created_at DESC LIMIT 1
    """, (invoice_id, session['user_id']))
    link = cursor.fetchone()
    cursor.close()
    db.close()
    
    if link:
        return jsonify({
            'checkout_url': link['checkout_url'],
            'amount': float(link['amount']),
            'reference': link['reference_number']
        })
    return jsonify({'error': 'No payment link found'}), 404

@payments_bp.route('/qr/<path:checkout_url_base64>')
def qr_code(checkout_url_base64):
    """Generate QR code for a checkout URL"""
    import base64 as b64
    try:
        url = b64.urlsafe_b64decode(checkout_url_base64.encode()).decode()
    except:
        return "Invalid URL", 400
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#10b981", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    
    return Response(buf.getvalue(), mimetype='image/png')

@payments_bp.route('/webhook/paymongo', methods=['POST'])
def paymongo_webhook():
    data = request.get_json()
    
    if not data or data.get('data', {}).get('attributes', {}).get('type') != 'payment.paid':
        return jsonify({'ok': True})
    
    attrs = data['data']['attributes']
    payment_data = attrs.get('data', {}).get('attributes', {})
    reference = payment_data.get('reference')
    
    if not reference:
        return jsonify({'ok': True})
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM payment_links WHERE reference_number = %s AND status = 'pending'", (reference,))
    link = cursor.fetchone()
    
    if link:
        amount = float(link['amount'])
        cursor.execute("""
            INSERT INTO payments (user_id, invoice_id, amount, payment_date, payment_method, reference_number)
            VALUES (%s, %s, %s, %s, 'online', %s)
        """, (link['user_id'], link['invoice_id'], amount, date.today(), reference))
        cursor.execute("UPDATE payment_links SET status = 'paid', paid_at = NOW() WHERE id = %s", (link['id'],))
        cursor.execute("""
            INSERT INTO transactions (user_id, description, amount, type, category, transaction_date)
            VALUES (%s, %s, %s, 'income', 'Online Payment', %s)
        """, (link['user_id'], "Online payment", amount, date.today()))
        db.commit()
    
    cursor.close()
    db.close()
    return jsonify({'ok': True})
@payments_bp.route('/gcash_qr/<int:invoice_id>')
def gcash_qr(invoice_id):
    """Generate a direct GCash QR code for an invoice"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    # Get the business's GCash number
    cursor.execute("SELECT gcash_number FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    gcash_number = user['gcash_number'] if user and user.get('gcash_number') else None
    
    if not gcash_number:
        cursor.close()
        db.close()
        flash('Please set your GCash number in Profile first.', 'error')
        return redirect(url_for('ar.ar'))
    
    # Get invoice
    cursor.execute("""
        SELECT i.*, c.name as customer_name
        FROM invoices i JOIN customers c ON i.customer_id = c.id
        WHERE i.id = %s AND i.user_id = %s
    """, (invoice_id, session['user_id']))
    invoice = cursor.fetchone()
    
    if not invoice:
        cursor.close()
        db.close()
        flash('Invoice not found.', 'error')
        return redirect(url_for('ar.ar'))
    
    cursor.execute("SELECT COALESCE(SUM(amount), 0) as total_paid FROM payments WHERE invoice_id = %s", (invoice_id,))
    total_paid = float(cursor.fetchone()['total_paid'])
    remaining = float(invoice['amount']) - total_paid
    
    cursor.close()
    db.close()
    
    # Generate GCash deep link
    # Format: gcash://send?to=09XXXXXXXXX&amount=XXX.XX&message=INV-XXX
    gcash_url = f"gcash://send?to={gcash_number}&amount={remaining:.2f}&message=INV-{invoice.get('invoice_number', str(invoice_id))}"
    
    # Also generate a web fallback URL
    web_url = f"https://gcash.app/send?to={gcash_number}&amount={remaining:.2f}"
    
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(gcash_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#007bff", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    
    return Response(buf.getvalue(), mimetype='image/png')

@payments_bp.route('/maya_qr/<int:invoice_id>')
def maya_qr(invoice_id):
    """Generate a direct Maya QR code for an invoice"""
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    db = get_db()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT maya_number FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    maya_number = user['maya_number'] if user and user.get('maya_number') else None
    
    if not maya_number:
        cursor.close()
        db.close()
        flash('Please set your Maya number in Profile first.', 'error')
        return redirect(url_for('ar.ar'))
    
    cursor.execute("""
        SELECT i.*, COALESCE(SUM(p.amount), 0) as total_paid
        FROM invoices i LEFT JOIN payments p ON i.id = p.invoice_id
        WHERE i.id = %s AND i.user_id = %s
        GROUP BY i.id
    """, (invoice_id, session['user_id']))
    invoice = cursor.fetchone()
    
    if not invoice:
        cursor.close()
        db.close()
        return "Invoice not found", 404
    
    remaining = float(invoice['amount']) - float(invoice['total_paid'])
    cursor.close()
    db.close()
    
    # Maya deep link
    maya_url = f"maya://send?to={maya_number}&amount={remaining:.2f}"
    
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(maya_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#00c853", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    
    return Response(buf.getvalue(), mimetype='image/png')
