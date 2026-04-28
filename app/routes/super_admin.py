from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.auth import admin_required, super_admin_required
from app.core.firebase import db, firestore, firebase_auth
from app.core.mqtt import mqtt_bridge
from app.core.utils import log_action, get_all_devices_with_state, _fb_get_count, _fb_get_logs_today, _fb_get_recent_logs
from app.core.dynamic_data import get_active_devices, get_active_rooms, get_free_pins, load_dynamic_data, DYNAMIC_BOARDS, DYNAMIC_ROOMS, _dynamic_lock, DEVICE_TYPE_ICONS, check_board_online
from app.core.hardware import cache

# To maintain backwards compatibility if `_sync_legacy` was called
def _sync_legacy(): pass

super_bp = Blueprint('super', __name__, url_prefix='/super')

@super_bp.route('/dashboard')
@super_admin_required
def dashboard():
    devices = get_active_devices()
    rooms = get_active_rooms()
    states = cache.get_all()
    on_count = sum(1 for k in devices if states.get(k, False))
    boards_info = []
    with _dynamic_lock:
        for bid, b in DYNAMIC_BOARDS.items():
            boards_info.append({**b, 'id': bid, 'online': check_board_online(bid)})
    active_timers = []
    try:
        tdocs = db.collection('timers').where(filter=FieldFilter('status', '==', 'active')).get()
        active_timers = [{**d.to_dict(), 'id': d.id} for d in tdocs]
    except Exception:
        pass

    return render_template('super/dashboard.html',
        user=session['user'], boards=boards_info, rooms=rooms,
        devices_count=len(devices), rooms_count=len(rooms),
        devices_on=on_count, active_timers=len(active_timers),
        users_count=_fb_get_count('users'), logs_today=_fb_get_logs_today(),
        recent_logs=_fb_get_recent_logs(8),
        mqtt_connected=mqtt_bridge.is_connected()
    )

@super_bp.route('/boards', methods=['GET', 'POST'])
@admin_required
def boards():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        board_type = request.form.get('board_type', 'esp32')
        blynk_template_id = request.form.get('blynk_template_id', '').strip()
        blynk_template_name = request.form.get('blynk_template_name', '').strip()
        blynk_token = request.form.get('blynk_token', '').strip()
        mqtt_prefix = request.form.get('mqtt_topic_prefix', '').strip()
        wifi_ssid = request.form.get('wifi_ssid', '').strip()

        if not all([name, blynk_token]):
            flash('Board name and Blynk token are required.', 'danger')
            return redirect(url_for('super.boards'))

        board_id = name.lower().replace(' ', '_') + '_board'
        db.collection('boards').document(board_id).set({
            'name': name, 'board_type': board_type,
            'blynk_template_id': blynk_template_id,
            'blynk_template_name': blynk_template_name,
            'blynk_token': blynk_token,
            'mqtt_topic_prefix': mqtt_prefix or f'{name.lower()}/relay/',
            'wifi_ssid': wifi_ssid, 'status': 'unknown',
            'last_seen': None, 'ip_address': '', 'rssi': 0,
            'created_at': datetime.now()
        })
        load_dynamic_data()
        log_action(f'Registered board: {name} ({board_type})')
        flash(f'Board "{name}" registered!', 'success')
        return redirect(url_for('super.boards'))

    boards_list = []
    with _dynamic_lock:
        for bid, b in DYNAMIC_BOARDS.items():
            free = get_free_pins(bid)
            boards_list.append({**b, 'id': bid, 'online': check_board_online(bid), 'free_pins': free})
    return render_template('super/boards.html', user=session['user'], boards=boards_list)

@super_bp.route('/boards/<board_id>/delete', methods=['POST'])
@admin_required
def delete_board(board_id):
    db.collection('boards').document(board_id).delete()
    load_dynamic_data()
    log_action(f'Deleted board: {board_id}')
    flash('Board deleted.', 'success')
    return redirect(url_for('super.boards'))

@super_bp.route('/boards/<board_id>/wifi', methods=['POST'])
@admin_required
def update_board_wifi(board_id):
    new_ssid = request.form.get('wifi_ssid', '').strip()
    new_pass = request.form.get('wifi_pass', '').strip()
    if not new_ssid:
        flash('WiFi SSID is required.', 'danger')
        return redirect(url_for('super.boards'))
    db.collection('boards').document(board_id).update({'wifi_ssid': new_ssid})
    if mqtt_bridge.is_connected():
        ok = mqtt_bridge.publish_wifi_config(board_id, new_ssid, new_pass)
        if ok:
            flash(f'WiFi credentials sent to {board_id}!', 'success')
        else:
            flash('WiFi config publish failed.', 'warning')
    else:
        flash('Board is offline — WiFi config saved but not sent.', 'warning')
    load_dynamic_data()
    log_action(f'Updated WiFi for board: {board_id}')
    return redirect(url_for('super.boards'))

@super_bp.route('/boards/<board_id>/status')
@admin_required
def board_status(board_id):
    online = check_board_online(board_id)
    with _dynamic_lock:
        board = DYNAMIC_BOARDS.get(board_id, {})
    if online:
        db.collection('boards').document(board_id).update({
            'status': 'online', 'last_seen': datetime.now()
        })
    return jsonify({'online': online, 'board': board.get('name', board_id)})

@super_bp.route('/rooms', methods=['GET', 'POST'])
@admin_required
def rooms():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        icon = request.form.get('icon', 'bi-house').strip()
        if not name:
            flash('Room name is required.', 'danger')
            return redirect(url_for('super.rooms'))
        existing = list(DYNAMIC_ROOMS.values())
        max_order = max((r.get('order', 0) for r in existing), default=-1) + 1
        room_id = name.lower().replace(' ', '_')
        db.collection('rooms').document(room_id).set({
            'name': name, 'icon': icon, 'order': max_order, 'created_at': datetime.now()
        })
        load_dynamic_data()
        log_action(f'Created room: {name}')
        flash(f'Room "{name}" created!', 'success')
        return redirect(url_for('super.rooms'))

    rooms_list = []
    with _dynamic_lock:
        for rid, r in sorted(DYNAMIC_ROOMS.items(), key=lambda x: x[1].get('order', 99)):
            devs = get_active_devices()
            dev_count = sum(1 for d in devs.values() if d.get('room') == r.get('name'))
            rooms_list.append({**r, 'id': rid, 'device_count': dev_count})
    return render_template('super/rooms.html', user=session['user'], rooms=rooms_list)

@super_bp.route('/rooms/<room_id>/delete', methods=['POST'])
@admin_required
def delete_room(room_id):
    with _dynamic_lock:
        room = DYNAMIC_ROOMS.get(room_id, {})
    db.collection('rooms').document(room_id).delete()
    load_dynamic_data()
    log_action(f'Deleted room: {room.get("name", room_id)}')
    flash('Room deleted.', 'success')
    return redirect(url_for('super.rooms'))

@super_bp.route('/devices', methods=['GET', 'POST'])
@admin_required
def devices():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        device_type = request.form.get('device_type', 'switch')
        room_name = request.form.get('room_name', '').strip()
        board_id = request.form.get('board_id', '')
        pin = request.form.get('pin', '')
        if not all([name, room_name, board_id, pin]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('super.devices'))
        icon = DEVICE_TYPE_ICONS.get(device_type, 'bi-plug')
        key = name.lower().replace(' ', '_').replace('(', '').replace(')', '')
        db.collection('devices').add({
            'key': key, 'name': name, 'device_type': device_type,
            'room_name': room_name, 'board_id': board_id,
            'pin': pin, 'icon': icon, 'type': 'blynk',
            'state': False, 'last_toggled': None, 'created_at': datetime.now()
        })
        load_dynamic_data()
        log_action(f'Added device: {name} in {room_name} on {board_id} pin {pin}')
        flash(f'Device "{name}" added!', 'success')
        return redirect(url_for('super.devices'))

    all_devs = get_all_devices_with_state()
    boards_list = []
    with _dynamic_lock:
        for bid, b in DYNAMIC_BOARDS.items():
            boards_list.append({**b, 'id': bid, 'free_pins': get_free_pins(bid)})
    rooms_list = get_active_rooms()
    return render_template('super/devices.html', user=session['user'],
        devices=all_devs, boards=boards_list, rooms=rooms_list,
        device_types=DEVICE_TYPE_ICONS)

@super_bp.route('/devices/<device_key>/delete', methods=['POST'])
@admin_required
def delete_device(device_key):
    try:
        docs = db.collection('devices').where(filter=FieldFilter('key', '==', device_key)).get()
        for doc in docs:
            doc.reference.delete()
    except Exception:
        pass
    load_dynamic_data()
    log_action(f'Deleted device: {device_key}')
    flash('Device deleted.', 'success')
    return redirect(url_for('super.devices'))

@super_bp.route('/api/force-toggle', methods=['POST'])
@admin_required
def force_toggle():
    from app.core.hardware import blynk_token_for_device, blynk_set
    data = request.get_json() or {}
    dev_key = data.get('device')
    state = data.get('state', False)
    devices = get_active_devices()
    dev = devices.get(dev_key)
    if not dev:
        return jsonify({'ok': False, 'error': 'Device not found'}), 404
    token = blynk_token_for_device(dev_key)
    ok = blynk_set(dev['pin'], 1 if state else 0, token=token)
    if ok:
        cache.set(dev_key, bool(state))
        log_action(f"FORCE {'ON' if state else 'OFF'}: {dev.get('name', dev_key)}", device_id=dev_key)
        try:
            docs = db.collection('devices').where(filter=FieldFilter('key', '==', dev_key)).limit(1).get()
            for d in docs:
                d.reference.update({'state': bool(state), 'last_toggled': datetime.now()})
        except Exception:
            pass
    return jsonify({'ok': ok})

@super_bp.route('/admins', methods=['GET', 'POST'])
@super_admin_required
def admins():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        full_name = request.form.get('full_name', '').strip()
        username = request.form.get('username', '').strip()
        role = request.form.get('role', 'admin')
        if not all([email, password, full_name, username]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('super.admins'))
        try:
            fb_user = firebase_auth.create_user(email=email, password=password, display_name=full_name)
            col = 'super_admin' if role == 'super_admin' else 'admin'
            db.collection(col).document(fb_user.uid).set({
                'username': username, 'full_name': full_name,
                'email': email, 'role': role, 'suspended': False,
                'created_at': datetime.now()
            })
            db.collection('users').document(fb_user.uid).set({
                'username': username, 'name': full_name,
                'email': email, 'role': role, 'suspended': False,
                'created_at': datetime.now()
            })
            log_action(f'Created admin: {email} ({role})')
            flash(f'Admin "{full_name}" created!', 'success')
        except Exception as e:
            flash(f'Error creating admin: {e}', 'danger')
        return redirect(url_for('super.admins'))

    admin_list = []
    try:
        for doc in db.collection('admin').get():
            d = doc.to_dict()
            if not d.get('_init'):
                admin_list.append({**d, 'id': doc.id, 'collection': 'admin'})
        for doc in db.collection('super_admin').get():
            d = doc.to_dict()
            if not d.get('_init'):
                admin_list.append({**d, 'id': doc.id, 'collection': 'super_admin'})
    except Exception:
        pass
    return render_template('super/admins.html', user=session['user'], admins=admin_list)

@super_bp.route('/admins/<admin_id>/delete', methods=['POST'])
@super_admin_required
def delete_admin(admin_id):
    col = request.form.get('collection', 'admin')
    try:
        firebase_auth.delete_user(admin_id)
    except Exception:
        pass
    db.collection(col).document(admin_id).delete()
    db.collection('users').document(admin_id).delete()
    log_action(f'Deleted admin: {admin_id}')
    flash('Admin account deleted.', 'success')
    return redirect(url_for('super.admins'))

@super_bp.route('/timers', methods=['GET', 'POST'])
@admin_required
def timers():
    if request.method == 'POST':
        device_id = request.form.get('device_id', '')
        action = request.form.get('action', 'off')
        duration = int(request.form.get('duration', '60'))
        devices = get_active_devices()
        dev = devices.get(device_id)
        if not dev:
            flash('Device not found.', 'danger')
            return redirect(url_for('super.timers'))
        now = datetime.now()
        end_time = now + timedelta(minutes=duration)
        db.collection('timers').add({
            'device_id': device_id, 'device_name': dev.get('name', device_id),
            'action': action, 'duration_minutes': duration,
            'start_time': now, 'end_time': end_time,
            'status': 'active', 'created_by': session['user']['username']
        })
        log_action(f"Timer set: {dev.get('name')} → {action.upper()} in {duration}min")
        flash(f'Timer set: {dev.get("name")} will turn {action.upper()} in {duration} minutes.', 'success')
        return redirect(url_for('super.timers'))

    active = []
    completed = []
    try:
        for doc in db.collection('timers').order_by('start_time', direction=firestore.Query.DESCENDING).limit(50).get():
            t = {**doc.to_dict(), 'id': doc.id}
            if t.get('status') == 'active':
                active.append(t)
            else:
                completed.append(t)
    except Exception:
        pass
    all_devs = get_all_devices_with_state()
    return render_template('super/timers.html', user=session['user'],
        active_timers=active, completed_timers=completed, devices=all_devs)

@super_bp.route('/timers/<timer_id>/cancel', methods=['POST'])
@admin_required
def cancel_timer(timer_id):
    db.collection('timers').document(timer_id).update({
        'status': 'cancelled', 'completed_at': datetime.now()
    })
    log_action(f'Cancelled timer: {timer_id}')
    flash('Timer cancelled.', 'success')
    return redirect(url_for('super.timers'))

@super_bp.route('/api/free-pins/<board_id>')
@admin_required
def api_free_pins(board_id):
    return jsonify({'pins': get_free_pins(board_id)})

@super_bp.route('/platform')
@super_admin_required
def platform():
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_users = ex.submit(_fb_get_count, 'users')
        f_homes = ex.submit(_fb_get_count, 'homes')
        f_devices = ex.submit(_fb_get_count, 'devices')
        f_logs = ex.submit(_fb_get_logs_today)
        users_count = f_users.result()
        homes_count = f_homes.result()
        devices_count = f_devices.result()
        logs_today = f_logs.result()
    boards_info = []
    with _dynamic_lock:
        for bid, b in DYNAMIC_BOARDS.items():
            boards_info.append({**b, 'id': bid, 'online': check_board_online(bid)})
    return render_template('super/platform.html',
        user=session['user'], users_count=users_count,
        homes_count=homes_count, devices_count=devices_count,
        logs_today=logs_today, mqtt_connected=mqtt_bridge.is_connected(),
        boards=boards_info
    )

@super_bp.route('/ota/push', methods=['POST'])
@super_admin_required
def ota_push():
    device_id = request.form.get('device_id', '')
    firmware_url = request.form.get('firmware_url', '')
    sha256 = request.form.get('sha256', '')
    if not all([device_id, firmware_url, sha256]):
        flash('All fields required for OTA push.', 'danger')
        return redirect(url_for('super.platform'))
    ok = mqtt_bridge.publish_ota(device_id, firmware_url, sha256)
    if ok:
        log_action(f'OTA push to {device_id}')
        flash(f'OTA firmware pushed to {device_id}', 'success')
    else:
        flash('OTA push failed — MQTT not connected.', 'danger')
    return redirect(url_for('super.platform'))

@super_bp.route('/wifi-manager')
@admin_required
def wifi_manager():
    """Centralized WiFi config page for all boards"""
    boards_list = []
    mqtt_states = mqtt_bridge.get_all_states()
    with _dynamic_lock:
        for bid, b in DYNAMIC_BOARDS.items():
            ms = mqtt_states.get(bid, {})
            boards_list.append({
                **b, 'id': bid,
                'online': ms.get('online', False) or check_board_online(bid),
                'wifi_ssid': ms.get('wifi_ssid', b.get('wifi_ssid', '')),
                'fw_version': ms.get('fw_version', ''),
                'rssi': ms.get('rssi', 0),
                'ip': ms.get('ip', ''),
                'device_name': ms.get('device_name', b.get('name', '')),
            })
    return render_template('super/wifi_manager.html', user=session['user'],
        boards=boards_list, mqtt_connected=mqtt_bridge.is_connected())
