import secrets
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.auth import admin_required
from app.core.firebase import db, firestore, firebase_auth
from app.core.mqtt import mqtt_bridge
from app.core.utils import log_action, get_all_devices_with_state, _fb_get_count, _fb_get_logs_today, _fb_get_recent_logs
from app.core.dynamic_data import get_active_devices, get_active_rooms
from app.core.hardware import cache

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_users = ex.submit(_fb_get_count, 'users')
        f_contacts = ex.submit(_fb_get_count, 'contact_us')
        f_logs_td = ex.submit(_fb_get_logs_today)
        f_rec_logs = ex.submit(_fb_get_recent_logs)
        users_count = f_users.result()
        contacts_count = f_contacts.result()
        logs_today = f_logs_td.result()
        recent_logs = f_rec_logs.result()

    states = cache.get_all()
    on_count = sum(1 for v in states.values() if v)
    devices = get_active_devices()
    rooms = get_active_rooms()

    return render_template('admin/dashboard.html',
        user=session['user'],
        users_count=users_count,
        logs_today=logs_today,
        contacts_count=contacts_count,
        recent_logs=recent_logs,
        devices_on=on_count,
        total_devices=len(devices),
        rooms=rooms,
        mqtt_connected=mqtt_bridge.is_connected()
    )

@admin_bp.route('/users')
@admin_required
def user_management():
    users = [dict(doc.to_dict(), id=doc.id) for doc in db.collection('users').get() if not doc.to_dict().get('_init')]
    return render_template('admin/user_management.html', user=session['user'], users=users)

@admin_bp.route('/users/delete/<uid>', methods=['POST'])
@admin_required
def delete_user(uid):
    try:
        firebase_auth.delete_user(uid)
    except Exception as e:
        print(f"Error deleting from Firebase Auth: {e}")
        flash(f'Warning: Firebase Auth deletion failed ({e}).', 'warning')
    
    db.collection('users').document(uid).delete()
    log_action(f'Deleted user {uid}')
    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/create', methods=['POST'])
@admin_required
def create_user():
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    full_name = request.form.get('full_name', '').strip()
    username = request.form.get('username', '').strip()
    role = request.form.get('role', 'user')

    if not email or not password or not username:
        flash('Email, password, and username are required.', 'danger')
        return redirect(url_for('admin.user_management'))

    try:
        user = firebase_auth.create_user(
            email=email,
            password=password,
            display_name=full_name
        )
        db.collection('users').document(user.uid).set({
            'full_name': full_name,
            'username': username,
            'email': email,
            'role': role,
            'suspended': False,
            'created_at': datetime.now()
        })
        log_action(f'Created user {email} as {role}')
        flash('User created successfully.', 'success')
    except Exception as e:
        flash(f'Failed to create user: {e}', 'danger')

    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/edit/<uid>', methods=['POST'])
@admin_required
def edit_user(uid):
    full_name = request.form.get('full_name', '').strip()
    username = request.form.get('username', '').strip()
    role = request.form.get('role', 'user')

    if not username:
        flash('Username cannot be empty.', 'danger')
        return redirect(url_for('admin.user_management'))

    try:
        firebase_auth.update_user(uid, display_name=full_name)
        db.collection('users').document(uid).update({
            'full_name': full_name,
            'username': username,
            'role': role
        })
        log_action(f'Updated user {uid}')
        flash('User updated successfully.', 'success')
    except Exception as e:
        flash(f'Failed to update user: {e}', 'danger')

    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/password/<uid>', methods=['POST'])
@admin_required
def change_user_password(uid):
    new_password = request.form.get('password', '')
    if len(new_password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin.user_management'))

    try:
        firebase_auth.update_user(uid, password=new_password)
        log_action(f'Changed password for user {uid}')
        flash('User password updated successfully.', 'success')
    except Exception as e:
        flash(f'Failed to update password: {e}', 'danger')

    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/suspend/<uid>', methods=['POST'])
@admin_required
def suspend_user(uid):
    db.collection('users').document(uid).update({'suspended': True})
    log_action(f'Suspended user {uid}')
    flash('User suspended.', 'success')
    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/unsuspend/<uid>', methods=['POST'])
@admin_required
def unsuspend_user(uid):
    db.collection('users').document(uid).update({'suspended': False})
    log_action(f'Unsuspended user {uid}')
    flash('User reactivated.', 'success')
    return redirect(url_for('admin.user_management'))

@admin_bp.route('/users/invite', methods=['POST'])
@admin_required
def invite_user():
    email = request.form.get('email', '').strip()
    role = request.form.get('role', 'user')
    room_ids = request.form.getlist('room_ids')

    if not email:
        flash('Email is required.', 'danger')
        return redirect(url_for('admin.user_management'))

    db.collection('permissions').add({
        'email': email,
        'role': role,
        'roomIds': room_ids,
        'homeId': session['user'].get('homeId', ''),
        'grantedBy': session['user']['id'],
        'createdAt': datetime.now(),
        'expiresAt': None
    })

    log_action(f'Invited {email} as {role}')
    flash(f'Invitation sent to {email}.', 'success')
    return redirect(url_for('admin.user_management'))

@admin_bp.route('/devices')
@admin_required
def device_management():
    status = get_all_devices_with_state()
    mqtt_devices = []
    rooms = get_active_rooms()
    try:
        mqtt_docs = db.collection('devices').limit(50).get()
        mqtt_devices = [{**doc.to_dict(), 'id': doc.id} for doc in mqtt_docs]
    except Exception:
        pass
    return render_template('admin/device_management.html',
        user=session['user'], devices=status, rooms=rooms,
        mqtt_devices=mqtt_devices)

@admin_bp.route('/devices/register', methods=['POST'])
@admin_required
def register_device():
    device_id = request.form.get('device_id', '').strip()
    name = request.form.get('name', '').strip()
    room = request.form.get('room', '').strip()

    if not device_id or not name:
        flash('Device ID and name are required.', 'danger')
        return redirect(url_for('admin.device_management'))

    device_secret = secrets.token_hex(16)
    db.collection('devices').document(device_id).set({
        'name': name,
        'room': room,
        'homeId': session['user'].get('homeId', 'default'),
        'roomId': '',
        'deviceSecret': device_secret,
        'status': 'offline',
        'lastSeen': None,
        'firmwareVersion': '1.0.0',
        'relayCount': 1,
        'locked': False,
        'createdAt': datetime.now()
    })

    log_action(f'Registered device {device_id}')
    flash(f'Device registered! Secret: {device_secret} — save this, it cannot be retrieved again.', 'success')
    return redirect(url_for('admin.device_management'))

@admin_bp.route('/logs')
@admin_required
def logs():
    # Initial load of 25 logs
    all_logs = [doc.to_dict() for doc in
        db.collection('logs').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(25).get()]
    return render_template('admin/logs.html', user=session['user'], logs=all_logs)

@admin_bp.route('/api/logs/more')
@admin_required
def api_more_logs():
    last_time_str = request.args.get('last_time')
    limit = int(request.args.get('limit', 25))
    
    query = db.collection('logs').order_by('timestamp', direction=firestore.Query.DESCENDING)
    
    if last_time_str:
        # Assuming timestamp is a string or we can convert it
        # If it's a datetime object, we'd need to parse it
        try:
            last_time = datetime.fromisoformat(last_time_str)
            query = query.start_after({'timestamp': last_time})
        except:
            pass
            
    docs = query.limit(limit).get()
    results = [doc.to_dict() for doc in docs]
    return jsonify(results)

@admin_bp.route('/notifications')
@admin_required
def notifications():
    contacts = [doc.to_dict() for doc in
        db.collection('contact_us').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(50).get()]
    return render_template('admin/notifications.html', user=session['user'], contact_requests=contacts)

@admin_bp.route('/profile', methods=['GET', 'POST'])
@admin_required
def profile():
    col = 'super_admin' if session['user']['role'] == 'super_admin' else 'admin'
    doc_ref = db.collection(col).document(session['user']['id'])
    doc = doc_ref.get()
    if request.method == 'POST':
        fn = request.form.get('full_name', '').strip()
        em = request.form.get('email', '').strip()
        if doc.exists:
            doc_ref.update({'full_name': fn, 'email': em})
        session['user']['name'] = fn
        flash('Profile updated!', 'success')
        return redirect(url_for('admin.profile'))
    raw = doc.to_dict() if doc.exists else {}
    a = {
        'id': session['user']['id'],
        'username': raw.get('username', session['user'].get('username', 'admin')),
        'full_name': raw.get('full_name', session['user'].get('name', 'Admin')),
        'email': raw.get('email', ''),
        'role': raw.get('role', session['user'].get('role', 'admin')),
        'created_at': raw.get('created_at', None)
    }
    return render_template('admin/profile.html', user=session['user'], admin=a)

@admin_bp.route('/reset-credentials')
@admin_required
def reset_credentials():
    return render_template('admin/reset_credentials.html', user=session['user'])

@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    if request.method == 'POST':
        # Simple settings update logic
        for key in request.form:
            val = request.form.get(key)
            db.collection('settings').document(key).set({'key_name': key, 'value': val})
        flash('Settings saved successfully.', 'success')
        return redirect(url_for('admin.settings'))
    
    s_docs = db.collection('settings').get()
    settings_data = {doc.to_dict().get('key_name'): doc.to_dict().get('value')
                     for doc in s_docs if not doc.to_dict().get('_init')}
    return render_template('admin/settings.html', user=session['user'], settings=settings_data)

@admin_bp.route('/settings/backup/download')
@admin_required
def download_backup():
    import json
    data = {
        'settings': [doc.to_dict() for doc in db.collection('settings').get()],
        'devices': [doc.to_dict() for doc in db.collection('devices').get()],
        'rooms': [doc.to_dict() for doc in db.collection('rooms').get()],
        'boards': [doc.to_dict() for doc in db.collection('boards').get()]
    }
    return jsonify(data), 200, {'Content-Disposition': 'attachment; filename=brighthaven_backup.json'}

@admin_bp.route('/settings/backup/restore', methods=['POST'])
@admin_required
def restore_backup():
    if 'backup_file' not in request.files:
        flash('No file uploaded.', 'danger')
        return redirect(url_for('admin.settings'))
    
    file = request.files['backup_file']
    if not file.filename.endswith('.json'):
        flash('Invalid file format. Please upload a .json backup.', 'danger')
        return redirect(url_for('admin.settings'))

    try:
        import json
        data = json.load(file)
        
        # Restore logic (overwrites)
        for col in ['settings', 'devices', 'rooms', 'boards']:
            if col in data:
                # Clear existing
                # (Optional: for simplicity in this demo, we just add/overwrite)
                for item in data[col]:
                    if 'id' in item:
                        db.collection(col).document(item['id']).set(item)
                    elif 'key' in item:
                         db.collection(col).document(item['key']).set(item)
                    else:
                        db.collection(col).add(item)
        
        flash('System restored successfully!', 'success')
    except Exception as e:
        flash(f'Restore failed: {e}', 'danger')
    
    return redirect(url_for('admin.settings'))

@admin_bp.route('/reports')
@admin_required
def reports():
    with ThreadPoolExecutor(max_workers=6) as ex:
        f_contacts = ex.submit(lambda: [d.to_dict() for d in db.collection('contact_us').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(50).get()])
        f_logs = ex.submit(lambda: [d.to_dict() for d in db.collection('logs').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(50).get()])
        f_users = ex.submit(lambda: [dict(d.to_dict(), id=d.id) for d in db.collection('users').get()])
        f_boards = ex.submit(lambda: [d.to_dict() for d in db.collection('boards').get()])
        f_rooms = ex.submit(lambda: [d.to_dict().get('name') for d in db.collection('rooms').order_by('order').get()])
        f_devs = ex.submit(get_all_devices_with_state)
        
        contacts = f_contacts.result()
        all_logs = f_logs.result()
        users = f_users.result()
        boards = f_boards.result()
        rooms = f_rooms.result()
        devices = f_devs.result()
        
    return render_template('admin/reports.html', user=session['user'],
        contacts=contacts, logs=all_logs, users=users, boards=boards, rooms=rooms, devices=devices)

@admin_bp.route('/monitoring')
@admin_required
def monitoring():
    return render_template('admin/monitoring.html', user=session['user'],
        mqtt_connected=mqtt_bridge.is_connected())

@admin_bp.route('/privacy')
@admin_required
def privacy():
    return render_template('admin/privacy.html', user=session['user'])

@admin_bp.route('/scenes', methods=['GET'])
@admin_required
def scenes():
    scene_docs = db.collection('scenes').get()
    all_scenes = [{**doc.to_dict(), 'id': doc.id} for doc in scene_docs]
    devices = get_active_devices()
    return render_template('admin/scenes.html', user=session['user'],
        scenes=all_scenes, devices=devices)

@admin_bp.route('/scenes/create', methods=['POST'])
@admin_required
def create_scene():
    name = request.form.get('name', '').strip()
    icon = request.form.get('icon', 'bi-magic')
    device_keys = request.form.getlist('devices')
    device_states = request.form.getlist('states')

    if not name:
        flash('Scene name is required.', 'danger')
        return redirect(url_for('admin.scenes'))

    actions = []
    for i, dk in enumerate(device_keys):
        actions.append({
            'device': dk,
            'state': device_states[i] == 'on' if i < len(device_states) else False
        })

    db.collection('scenes').add({
        'name': name,
        'icon': icon,
        'actions': actions,
        'createdBy': session['user']['id'],
        'createdAt': datetime.now()
    })

    log_action(f'Created scene: {name}')
    flash(f'Scene "{name}" created!', 'success')
    return redirect(url_for('admin.scenes'))

@admin_bp.route('/scheduler', methods=['GET'])
@admin_required
def scheduler():
    schedule_docs = db.collection('schedules').order_by('time').get()
    schedules = [{**doc.to_dict(), 'id': doc.id} for doc in schedule_docs]
    devices = get_active_devices()
    return render_template('admin/scheduler.html', user=session['user'],
        schedules=schedules, devices=devices)

@admin_bp.route('/scheduler/create', methods=['POST'])
@admin_required
def create_schedule():
    device = request.form.get('device', '')
    action = request.form.get('action', 'off')
    time_str = request.form.get('time', '')
    repeat = request.form.get('repeat', 'once')
    days = request.form.getlist('days')

    if not device or not time_str:
        flash('Device and time are required.', 'danger')
        return redirect(url_for('admin.scheduler'))

    db.collection('schedules').add({
        'device': device,
        'action': action,
        'time': time_str,
        'repeat': repeat,
        'days': days,
        'enabled': True,
        'createdBy': session['user']['id'],
        'createdAt': datetime.now()
    })

    log_action(f'Created schedule for {device} at {time_str}')
    flash('Schedule created!', 'success')
    return redirect(url_for('admin.scheduler'))

@admin_bp.route('/search')
@admin_required
def search():
    q = request.args.get('query', '').lower().strip()
    all_users = [dict(d.to_dict(), id=d.id) for d in db.collection('users').get()
                 if q in d.to_dict().get('username', '').lower() or q in d.to_dict().get('email', '').lower()]
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify([u['username'] for u in all_users])
    return render_template('admin/search_results.html', user=session['user'], query=q, users=all_users)
