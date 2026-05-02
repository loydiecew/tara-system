from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
from datetime import date, datetime
import requests
import base64
import os
from models.database import get_db
from models.email_service import send_email

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
    
    if session.get('plan') not in ['enterprise']:
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
    
    if session.get('plan') not in ['enterprise']:
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