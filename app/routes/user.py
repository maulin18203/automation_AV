import json
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, Response, stream_with_context
from google.cloud.firestore_v1.base_query import FieldFilter
from concurrent.futures import ThreadPoolExecutor

from app.core.auth import login_required
from app.core.firebase import db, firestore
from app.core.mqtt import mqtt_bridge
from app.core.utils import log_action
from app.core.dynamic_data import get_active_devices, get_active_rooms, _dynamic_lock, DYNAMIC_ROOMS
from app.core.hardware import cache, gpio_ctrl, blynk_token_for_device, blynk_set

user_bp = Blueprint('user', __name__, url_prefix='/user')

def _get_room_devices(room_name):
    devices = get_active_devices()
    return {k: v for k, v in devices.items() if v.get('room', '').lower() == room_name.lower()}

@user_bp.route('/dashboard')
@login_required
def dashboard():
    devices = get_active_devices()
    rooms = get_active_rooms()
    states = cache.get_all()
    on_count = sum(1 for k in devices if states.get(k, False))

    # Get user's scenes
    scenes = []
    try:
        scene_docs = db.collection('scenes').limit(10).get()
        scenes = [{**doc.to_dict(), 'id': doc.id} for doc in scene_docs]
    except Exception:
        pass

    return render_template('users/dashboard.html',
        user=session['user'],
        rooms=rooms,
        on_count=on_count,
        total=len(devices),
        scenes=scenes,
        all_devices=devices
    )

@user_bp.route('/room/<room_slug>')
@login_required
def dynamic_room(room_slug):
    """Dynamic room route — works with any room name"""
    room_name = room_slug.replace('-', ' ').title()
    rooms = get_active_rooms()
    matched = next((r for r in rooms if r.lower() == room_name.lower()), room_name)
    icon = 'bi-house'
    with _dynamic_lock:
        for r in DYNAMIC_ROOMS.values():
            if r.get('name', '').lower() == matched.lower():
                icon = r.get('icon', 'bi-house')
                break
    return render_template('users/room.html', user=session['user'],
        devices=_get_room_devices(matched), room_name=matched,
        room_icon=icon, room_slug=room_slug)

# Standardized route handlers using dynamic room logic to avoid duplication
@user_bp.route('/main-room')
@login_required
def main_room(): return dynamic_room('main-room')

@user_bp.route('/bedroom-1')
@login_required
def bedroom_1(): return dynamic_room('bedroom-1')

@user_bp.route('/bedroom-2')
@login_required
def bedroom_2(): return dynamic_room('bedroom-2')

@user_bp.route('/bedroom-3')
@login_required
def bedroom_3(): return dynamic_room('bedroom-3')

@user_bp.route('/kitchen')
@login_required
def kitchen(): return dynamic_room('kitchen')

@user_bp.route('/main-switch')
@login_required
def main_switch():
    states = cache.get_all()
    rooms_status = {}
    devices = get_active_devices()
    for room in get_active_rooms():
        rooms_status[room] = any(states.get(k, False) for k, v in devices.items() if v['room'] == room)
    return render_template('users/main_switch.html', user=session['user'], rooms=rooms_status)

@user_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    doc_ref = db.collection('users').document(session['user']['id'])
    doc = doc_ref.get()
    if request.method == 'POST':
        fn = request.form.get('full_name', '').strip()
        em = request.form.get('email', '').strip()
        ph = request.form.get('phone', '').strip()
        if doc.exists:
            doc_ref.update({'full_name': fn, 'email': em, 'phone': ph})
        session['user']['name'] = fn
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('user.profile'))
    raw = doc.to_dict() if doc.exists else {}
    u = {
        'id': session['user']['id'],
        'username': raw.get('username', session['user'].get('username', 'user')),
        'full_name': raw.get('full_name', session['user'].get('name', 'User')),
        'email': raw.get('email', ''),
        'phone': raw.get('phone', ''),
        'created_at': raw.get('created_at', None)
    }
    return render_template('users/profile.html', user=session['user'], profile=u)

@user_bp.route('/notifications')
@login_required
def notifications():
    try:
        docs = db.collection('notifications').where(
            filter=FieldFilter('user_id', '==', session['user']['id'])
        ).order_by('timestamp', direction=firestore.Query.DESCENDING).limit(50).get()
        notifs = [d.to_dict() for d in docs]
    except Exception:
        notifs = []
    return render_template('users/notifications.html', user=session['user'], notifications=notifs)

@user_bp.route('/reset-credentials')
@login_required
def reset_credentials():
    return render_template('users/reset_credentials.html', user=session['user'])

@user_bp.route('/search')
@login_required
def search():
    q = request.args.get('query', '').lower().strip()
    devices = get_active_devices()
    results = [{'id': k, **v} for k, v in devices.items()
               if q in v['name'].lower() or q in v['room'].lower()]
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify([r['name'] for r in results])
    return render_template('users/search_results.html', user=session['user'], query=q, results=results)

# ─── USER API ─────────────────────────────────────────────────────────────────

@user_bp.route('/api/toggle', methods=['POST'])
@login_required
def toggle():
    data = request.get_json() or {}
    dev_key = data.get('device')
    devices = get_active_devices()
    dev = devices.get(dev_key)
    if not dev:
        return jsonify({'ok': False, 'error': 'Unknown device'}), 404

    state = data.get('state')

    if dev.get('type') == 'gpio':
        ok = gpio_ctrl.set_pin(dev['pin'], state)
    elif dev.get('type') == 'mqtt':
        ok = mqtt_bridge.publish_command(dev_key, 0, state)
    else:
        token = blynk_token_for_device(dev_key)
        ok = blynk_set(dev['pin'], 1 if state else 0, token=token)

    if ok:
        cache.set(dev_key, bool(state))
        log_action(f"{'ON' if state else 'OFF'}: {dev['room']} - {dev['name']}", device_id=dev_key)

    return jsonify({'ok': ok})

@user_bp.route('/api/toggle-room', methods=['POST'])
@login_required
def toggle_room():
    data = request.get_json() or {}
    room = data.get('room')
    state = data.get('state')
    devices = get_active_devices()
    room_devices = [(k, v) for k, v in devices.items() if v['room'] == room]

    def _set_one(item):
        k, d = item
        if d.get('type') == 'gpio':
            ok = gpio_ctrl.set_pin(d['pin'], state)
        elif d.get('type') == 'mqtt':
            ok = mqtt_bridge.publish_command(k, 0, state)
        else:
            token = blynk_token_for_device(k)
            ok = blynk_set(d['pin'], 1 if state else 0, token=token)
        if ok:
            cache.set(k, bool(state))
        return ok

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(_set_one, room_devices))

    log_action(f"{'ON' if state else 'OFF'}: All devices in {room}")
    return jsonify({'ok': True, 'count': len(room_devices)})

@user_bp.route('/api/toggle-all', methods=['POST'])
@login_required
def toggle_all():
    state = (request.get_json() or {}).get('state')
    devices = get_active_devices()

    def _set_one(item):
        k, d = item
        if d.get('type') == 'gpio':
            ok = gpio_ctrl.set_pin(d['pin'], state)
        elif d.get('type') == 'mqtt':
            ok = mqtt_bridge.publish_command(k, 0, state)
        else:
            token = blynk_token_for_device(k)
            ok = blynk_set(d['pin'], 1 if state else 0, token=token)
        if ok:
            cache.set(k, bool(state))
        return ok

    with ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(_set_one, devices.items()))

    log_action(f"{'ON' if state else 'OFF'}: ALL devices")
    return jsonify({'ok': True})

@user_bp.route('/api/status')
@login_required
def device_status():
    return jsonify(cache.get_all())

@user_bp.route('/api/scene/activate', methods=['POST'])
@login_required
def activate_scene():
    """Activate a named scene — applies all device states defined in the scene"""
    data = request.get_json() or {}
    scene_id = data.get('scene_id')
    if not scene_id:
        return jsonify({'ok': False, 'error': 'No scene_id'}), 400

    try:
        doc = db.collection('scenes').document(scene_id).get()
        if not doc.exists:
            return jsonify({'ok': False, 'error': 'Scene not found'}), 404

        scene = doc.to_dict()
        actions = scene.get('actions', [])
        devices = get_active_devices()

        for action in actions:
            dev_key = action.get('device')
            state = action.get('state', False)
            dev = devices.get(dev_key)
            if dev:
                if dev.get('type') == 'gpio':
                    gpio_ctrl.set_pin(dev['pin'], state)
                else:
                    token = blynk_token_for_device(dev_key)
                    blynk_set(dev['pin'], 1 if state else 0, token=token)
                cache.set(dev_key, bool(state))

        log_action(f"Scene activated: {scene.get('name', 'Unknown')}")
        return jsonify({'ok': True, 'name': scene.get('name')})

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@user_bp.route('/api/sse')
@login_required
def sse_stream():
    """Server-Sent Events stream for real-time device updates"""
    def generate():
        q = mqtt_bridge.subscribe_sse()
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                try:
                    event = q.get(timeout=30)
                    yield f"data: {json.dumps(event)}\n\n"
                except Exception:
                    yield f": keepalive\n\n"
        finally:
            mqtt_bridge.unsubscribe_sse(q)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )
