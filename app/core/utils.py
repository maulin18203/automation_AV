import os
import smtplib
from email.message import EmailMessage
from datetime import datetime
from flask import session, request
from app.core.firebase import db

# ─── EMAIL HELPERS ────────────────────────────────────────────────────────────
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASS = os.getenv('SMTP_PASS', '')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@brighthaven.com')

def send_email(to_email, subject, body):
    if not SMTP_USER or not SMTP_PASS:
        print(f"\n[EMAIL MOCK] To: {to_email}\nSubject: {subject}\n{body}\n")
        return False
        
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = to_email

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send email to {to_email}: {e}")
        return False

from concurrent.futures import ThreadPoolExecutor

_log_executor = ThreadPoolExecutor(max_workers=2)

# ─── LOG HELPERS ──────────────────────────────────────────────────────────────
def log_action(action, device_id=None, relay=None):
    """Log an action asynchronously to Firestore"""
    if 'user' not in session:
        return
    username = session['user']['username']
    user_id = session['user']['id']
    ip_addr = request.remote_addr
    tenant_id = session['user'].get('tenant_id', 'tenant_default_001')

    def _write():
        try:
            db.collection('logs').add({
                'username': username,
                'userId': user_id,
                'tenant_id': tenant_id,
                'action': action,
                'deviceId': device_id,
                'relay': relay,
                'ip_address': ip_addr,
                'timestamp': datetime.now()
            })
        except Exception:
            pass

    _log_executor.submit(_write)

def get_all_devices_with_state():
    from app.core.dynamic_data import get_active_devices
    from app.core.hardware import cache
    devices = get_active_devices()
    states = cache.get_all()
    return {k: {**v, 'state': states.get(k, False)} for k, v in devices.items()}

def _fb_get_count(collection):
    from flask import g
    tid = getattr(g, 'tenant_id', 'tenant_default_001')
    from google.cloud.firestore_v1.base_query import FieldFilter
    res = db.collection(collection).where(filter=FieldFilter('tenant_id', '==', tid)).count().get()
    return res[0][0].value if res else 0

def _fb_get_logs_today():
    from flask import g
    tid = getattr(g, 'tenant_id', 'tenant_default_001')
    today_start = datetime.combine(datetime.now().date(), datetime.min.time())
    from google.cloud.firestore_v1.base_query import FieldFilter
    res = db.collection('logs').where(filter=FieldFilter('tenant_id', '==', tid))\
                               .where(filter=FieldFilter('timestamp', '>=', today_start)).count().get()
    return res[0][0].value if res else 0

def _fb_get_recent_logs(limit=10):
    from flask import g
    tid = getattr(g, 'tenant_id', 'tenant_default_001')
    from google.cloud.firestore_v1.base_query import FieldFilter
    from app.core.firebase import firestore
    return [doc.to_dict() for doc in db.collection('logs')\
            .where(filter=FieldFilter('tenant_id', '==', tid))\
            .order_by('timestamp', direction=firestore.Query.DESCENDING).limit(limit).get()]
