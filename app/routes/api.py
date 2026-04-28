from flask import Blueprint, request, jsonify, session
from datetime import datetime

from app.core.auth import login_required, admin_required, super_admin_required
from app.core.firebase import db
from app.core.mqtt import mqtt_bridge
from app.core.utils import log_action
from app.core.dynamic_data import get_active_devices, DYNAMIC_BOARDS, _dynamic_lock, check_board_online
from app.core.hardware import cache

api_bp = Blueprint('api', __name__)

@api_bp.route('/api/boards/status')
@login_required
def api_boards_status():
    """Return all boards with online/offline, WiFi SSID, firmware version, room"""
    boards_out = []
    with _dynamic_lock:
        for bid, b in DYNAMIC_BOARDS.items():
            mqtt_state = mqtt_bridge.get_device_state(bid)
            boards_out.append({
                'id': bid,
                'name': b.get('name', bid),
                'board_type': b.get('board_type', 'esp32'),
                'online': mqtt_state.get('online', False) or check_board_online(bid),
                'wifi_ssid': mqtt_state.get('wifi_ssid', b.get('wifi_ssid', '')),
                'blynk_token': b.get('blynk_token', '')[:8] + '...' if b.get('blynk_token') else '',
                'fw_version': mqtt_state.get('fw_version', ''),
                'rssi': mqtt_state.get('rssi', 0),
                'uptime': mqtt_state.get('uptime', 0),
                'free_heap': mqtt_state.get('free_heap', 0),
                'ip': mqtt_state.get('ip', b.get('ip_address', '')),
                'device_name': mqtt_state.get('device_name', b.get('name', '')),
                'last_seen': str(mqtt_state.get('lastSeen', '')) if mqtt_state.get('lastSeen') else None,
            })
    return jsonify(boards_out)

@api_bp.route('/api/boards/<board_id>/wifi', methods=['POST'])
@admin_required
def api_board_wifi(board_id):
    """Push WiFi credentials to ESP via MQTT (JSON API)"""
    data = request.get_json() or {}
    ssid = data.get('ssid', '').strip()
    password = data.get('password', '').strip()
    if not ssid:
        return jsonify({'ok': False, 'error': 'SSID required'}), 400
    db.collection('boards').document(board_id).update({'wifi_ssid': ssid})
    ok = mqtt_bridge.publish_wifi_config(board_id, ssid, password)
    log_action(f'WiFi config pushed to {board_id}: {ssid}')
    return jsonify({'ok': ok, 'board_id': board_id, 'ssid': ssid})

@api_bp.route('/api/boards/<board_id>/name', methods=['POST'])
@admin_required
def api_board_name(board_id):
    """Change ESP device name remotely via MQTT"""
    data = request.get_json() or {}
    new_name = data.get('name', '').strip()
    if not new_name:
        return jsonify({'ok': False, 'error': 'Name required'}), 400
    ok = mqtt_bridge.publish_device_config(board_id, {'device_name': new_name})
    if ok:
        db.collection('boards').document(board_id).update({'device_name': new_name})
    log_action(f'Renamed board {board_id} to {new_name}')
    return jsonify({'ok': ok})

@api_bp.route('/api/boards/<board_id>/ota', methods=['POST'])
@super_admin_required
def api_board_ota(board_id):
    """Trigger OTA update on a specific board"""
    data = request.get_json() or {}
    url = data.get('url', '').strip()
    sha256 = data.get('sha256', '').strip()
    if not url:
        return jsonify({'ok': False, 'error': 'Firmware URL required'}), 400
    ok = mqtt_bridge.publish_ota(board_id, url, sha256)
    if ok:
        db.collection('boards').document(board_id).update({
            'ota_status': 'updating', 'ota_started': datetime.now()
        })
    log_action(f'OTA triggered for {board_id}')
    return jsonify({'ok': ok})

@api_bp.route('/api/boards/<board_id>/reset', methods=['POST'])
@super_admin_required
def api_board_reset(board_id):
    """Send factory reset command via MQTT"""
    ok = mqtt_bridge.publish_factory_reset(board_id)
    log_action(f'Factory reset sent to {board_id}')
    return jsonify({'ok': ok})

@api_bp.route('/api/boards/all-tokens')
@super_admin_required
def api_all_tokens():
    """Return all Blynk tokens from Firebase (super admin only)"""
    tokens = []
    with _dynamic_lock:
        for bid, b in DYNAMIC_BOARDS.items():
            tokens.append({
                'board_id': bid, 'name': b.get('name', bid),
                'blynk_token': b.get('blynk_token', ''),
                'blynk_template_id': b.get('blynk_template_id', ''),
                'blynk_template_name': b.get('blynk_template_name', ''),
            })
    return jsonify(tokens)

@api_bp.route('/api/devices/connected')
@login_required
def api_devices_connected():
    """Return all connected ESP devices with status info"""
    mqtt_states = mqtt_bridge.get_all_states()
    devices = get_active_devices()
    blynk_states = cache.get_all()
    result = []
    with _dynamic_lock:
        for bid, b in DYNAMIC_BOARDS.items():
            ms = mqtt_states.get(bid, {})
            online = ms.get('online', False) or check_board_online(bid)
            room_devices = []
            for dk, dv in devices.items():
                if dv.get('board_id') == bid:
                    room_devices.append({
                        'key': dk, 'name': dv.get('name', dk),
                        'room': dv.get('room', ''), 'pin': dv.get('pin', ''),
                        'state': blynk_states.get(dk, False),
                    })
            result.append({
                'board_id': bid, 'name': b.get('name', bid),
                'board_type': b.get('board_type', 'esp32'),
                'online': online,
                'wifi_ssid': ms.get('wifi_ssid', b.get('wifi_ssid', '')),
                'fw_version': ms.get('fw_version', ''),
                'rssi': ms.get('rssi', 0),
                'uptime': ms.get('uptime', 0),
                'ip': ms.get('ip', ''),
                'devices': room_devices,
                'device_count': len(room_devices),
            })
    return jsonify(result)

@api_bp.route('/esp/status')
def esp_status():
    return jsonify(cache.get_all())

@api_bp.route('/api/mqtt/status')
def mqtt_status():
    return jsonify({
        'connected': mqtt_bridge.is_connected(),
        'devices': mqtt_bridge.get_all_states()
    })
