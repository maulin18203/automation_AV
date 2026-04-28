from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime
from google.cloud.firestore_v1.base_query import FieldFilter
from app.core.firebase import db, firebase_auth
from app.core.utils import log_action, send_email, ADMIN_EMAIL

home_bp = Blueprint('home', __name__)

@home_bp.route('/', methods=['GET', 'POST'])
@home_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        role = session['user']['role']
        if role in ('super_admin', 'admin'):
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('user.dashboard'))
    return render_template('login.html')

@home_bp.route('/api/getEmailFromUsername', methods=['POST'])
def get_email_from_username():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    if not username:
        return jsonify({'status': 'error', 'message': 'Username required'}), 400
    
    # Search all collections
    for col in ['super_admin', 'admin', 'users']:
        docs = db.collection(col).where(filter=FieldFilter('username', '==', username)).limit(1).get()
        if docs:
            return jsonify({'status': 'success', 'email': docs[0].to_dict().get('email')})
            
    return jsonify({'status': 'error', 'message': 'User not found'}), 404

@home_bp.route('/api/sessionLogin', methods=['POST'])
def session_login():
    """Verify Firebase ID token and establish Flask session"""
    id_token = request.json.get('idToken')
    if not id_token:
        return {'status': 'error', 'message': 'No token provided'}, 400

    try:
        decoded = firebase_auth.verify_id_token(id_token)
        email = decoded.get('email')
        uid = decoded.get('uid')
        
        if not email:
            return {'status': 'error', 'message': 'Token missing email'}, 400

        # Check collections for this email
        # 1. super_admin
        sup = db.collection('super_admin').where(filter=FieldFilter('email', '==', email)).limit(1).get()
        if sup:
            res = sup[0].to_dict()
            session['user'] = {'id': sup[0].id, 'email': email, 'username': res.get('username',''), 'role': 'super_admin', 'name': res.get('full_name'), 'tenant_id': res.get('tenant_id', 'tenant_default_001')}
            session.permanent = True
            return {'status': 'success', 'redirect': url_for('admin.dashboard')}

        # 2. admin
        adm = db.collection('admin').where(filter=FieldFilter('email', '==', email)).limit(1).get()
        if adm:
            res = adm[0].to_dict()
            session['user'] = {'id': adm[0].id, 'email': email, 'username': res.get('username',''), 'role': 'admin', 'name': res.get('full_name'), 'tenant_id': res.get('tenant_id', 'tenant_default_001')}
            session.permanent = True
            return {'status': 'success', 'redirect': url_for('admin.dashboard')}

        # 3. users
        usr = db.collection('users').where(filter=FieldFilter('email', '==', email)).limit(1).get()
        if usr:
            res = usr[0].to_dict()
            if res.get('suspended'):
                return {'status': 'error', 'message': 'Account suspended'}, 403
            session['user'] = {'id': usr[0].id, 'email': email, 'username': res.get('username',''), 'role': 'user', 'name': res.get('full_name'), 'tenant_id': res.get('tenant_id', 'tenant_default_001')}
            session.permanent = True
            return {'status': 'success', 'redirect': url_for('user.dashboard')}

        return {'status': 'error', 'message': 'User profile not found in database'}, 404

    except Exception as e:
        print(f"[Auth Error] {e}")
        return {'status': 'error', 'message': str(e)}, 401

@home_bp.route('/signup')
def signup():
    return render_template('signup.html')

@home_bp.route('/api/register', methods=['POST'])
def api_register():
    """Create user profile in Firestore after Firebase Auth signup"""
    data = request.json
    uid = data.get('uid')
    em = data.get('email')
    fn = data.get('full_name', '')
    un = data.get('username', '')
    ph = data.get('phone', '')

    if not uid or not em:
        return {'status': 'error', 'message': 'Missing data'}, 400

    # Ensure uniqueness of username
    if un and db.collection('users').where(filter=FieldFilter('username', '==', un)).limit(1).get():
        return {'status': 'error', 'message': 'Username taken'}, 400

    # Create profile
    db.collection('users').document(uid).set({
        'full_name': fn,
        'username': un,
        'email': em,
        'phone': ph,
        'suspended': False,
        'created_at': datetime.now()
    })
    return {'status': 'success'}

@home_bp.route('/logout')
def logout():
    log_action('Logout')
    session.clear()
    return redirect(url_for('home.login'))

@home_bp.route('/forgot-password')
def forgot_password():
    return render_template('forgot_password.html')

@home_bp.route('/contact', methods=['GET', 'POST'])
def contact_us():
    if request.method == 'POST':
        name = request.form.get('name', '')
        email = request.form.get('email', '')
        subj = request.form.get('subject', '')
        msg = request.form.get('message', '')
        
        # Save to Firebase
        db.collection('contact_us').add({
            'username': name,
            'email': email,
            'subject': subj,
            'message': msg,
            'timestamp': datetime.now()
        })
        
        # Send Email to Admin
        body = f"New Contact Request from BrightHaven:\n\nName: {name}\nEmail: {email}\n\nMessage:\n{msg}"
        send_email(ADMIN_EMAIL, f"Contact Form: {subj}", body)
        
        flash('Message sent successfully! We will get back to you shortly.', 'success')
    return render_template('contact_us.html')
