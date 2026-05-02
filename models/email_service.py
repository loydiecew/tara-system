from flask_mail import Message
from flask import current_app, session
from models.database import get_db
import smtplib

def get_user_smtp():
    """Get the user's SMTP settings, or fall back to system defaults"""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT smtp_email, smtp_password, business_name FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.close()
    db.close()
    
    if user and user.get('smtp_email') and user.get('smtp_password'):
        return {
            'email': user['smtp_email'],
            'password': user['smtp_password'],
            'name': user.get('business_name', 'TARA')
        }
    else:
        return {
            'email': current_app.config['MAIL_USERNAME'],
            'password': current_app.config['MAIL_PASSWORD'],
            'name': 'TARA System'
        }

def send_email(to_email, subject, html_body):
    """Send an email using user's SMTP if set, otherwise system default"""
    try:
        smtp = get_user_smtp()
        
        msg = Message(
            subject=subject,
            recipients=[to_email],
            html=html_body,
            sender=(smtp['name'], smtp['email'])
        )
        
        # Use smtplib directly with user's credentials
        with smtplib.SMTP(current_app.config['MAIL_SERVER'], current_app.config['MAIL_PORT']) as server:
            server.starttls()
            server.login(smtp['email'], smtp['password'])
            # Convert Flask-Mail message to email Message
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            
            email_msg = MIMEMultipart()
            email_msg['Subject'] = subject
            email_msg['From'] = f"{smtp['name']} <{smtp['email']}>"
            email_msg['To'] = to_email
            email_msg.attach(MIMEText(html_body, 'html'))
            
            server.send_message(email_msg)
        
        return True, "Email sent successfully"
    except Exception as e:
        return False, str(e)

def send_quote_email(quote, customer_name, customer_email, business_name):
    """Send a quotation email"""
    subject = f"Quotation {quote['quote_number']} from {business_name}"
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #10b981, #059669); padding: 24px; border-radius: 12px 12px 0 0;">
            <h2 style="color: white; margin: 0;">{business_name}</h2>
            <p style="color: rgba(255,255,255,0.8); margin: 4px 0 0;">Quotation {quote['quote_number']}</p>
        </div>
        <div style="background: #f8fafc; padding: 24px; border: 1px solid #e2e8f0;">
            <p>Dear {customer_name},</p>
            <p>Thank you for your interest. Here's your quotation:</p>
            <div style="background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin: 16px 0;">
                <table style="width:100%">
                    <tr><td style="color:#64748b;padding:4px 0;">Quote Number</td><td style="font-weight:600;text-align:right;">{quote['quote_number']}</td></tr>
                    <tr><td style="color:#64748b;padding:4px 0;">Date</td><td style="font-weight:600;text-align:right;">{quote['quote_date']}</td></tr>
                    <tr><td style="color:#64748b;padding:4px 0;">Valid Until</td><td style="font-weight:600;text-align:right;">{quote.get('valid_until', 'Not specified')}</td></tr>
                    <tr><td style="color:#64748b;padding:4px 0;">Total Amount</td><td style="font-weight:700;font-size:18px;color:#10b981;text-align:right;">₱ {quote['total_amount']:,.2f}</td></tr>
                </table>
            </div>
            <div style="margin-top: 24px; text-align: center;">
                <a href="http://127.0.0.1:5000/quote/action/{quote['id']}/accepted" style="background: #10b981; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; display: inline-block; margin-right: 8px; font-weight: 600;">Accept Quote</a>
                <a href="http://127.0.0.1:5000/quote/action/{quote['id']}/rejected" style="background: #ef4444; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; display: inline-block; margin-right: 8px; font-weight: 600;">Reject Quote</a>
                <a href="http://127.0.0.1:5000/view_quote/{quote['id']}" style="background: #f1f5f9; color: #64748b; padding: 12px 24px; border-radius: 8px; text-decoration: none; display: inline-block; font-weight: 600;">View Online</a>
            </div>
        </div>
        <div style="text-align:center;padding:16px;color:#94a3b8;font-size:12px;">Sent via TARA Accounting System</div>
    </div>
    """
    return send_email(customer_email, subject, html_body)
    
def send_invoice_email(invoice, customer_name, customer_email, business_name):
    """Send an invoice email"""
    subject = f"Invoice {invoice.get('invoice_number', '')} from {business_name}"
    
    html_body = f"""
    <div style="font-family: 'Inter', Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #10b981, #059669); padding: 24px; border-radius: 12px 12px 0 0;">
            <h2 style="color: white; margin: 0;">{business_name}</h2>
            <p style="color: rgba(255,255,255,0.8); margin: 4px 0 0;">Invoice from {business_name}</p>
        </div>
        
        <div style="background: #f8fafc; padding: 24px; border: 1px solid #e2e8f0; border-top: none;">
            <p>Dear {customer_name},</p>
            <p>Please find your invoice attached.</p>
            
            <div style="background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin: 16px 0;">
                <table style="width: 100%;">
                    <tr>
                        <td style="color: #64748b; padding: 4px 0;">Invoice Number</td>
                        <td style="font-weight: 600; text-align: right;">{invoice.get('invoice_number', 'N/A')}</td>
                    </tr>
                    <tr>
                        <td style="color: #64748b; padding: 4px 0;">Due Date</td>
                        <td style="font-weight: 600; text-align: right;">{invoice.get('due_date', 'N/A')}</td>
                    </tr>
                    <tr>
                        <td style="color: #64748b; padding: 4px 0;">Amount Due</td>
                        <td style="font-weight: 700; font-size: 18px; color: #10b981; text-align: right;">₱ {invoice['amount']:,.2f}</td>
                    </tr>
                </table>
            </div>
            
            <div style="margin-top: 20px;">
                <a href="#" style="background: #10b981; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; display: inline-block;">Pay Now</a>
            </div>
        </div>
        
        <div style="text-align: center; padding: 16px; color: #94a3b8; font-size: 12px;">
            Sent via TARA Accounting System
        </div>
    </div>
    """
    
    return send_email(customer_email, subject, html_body)