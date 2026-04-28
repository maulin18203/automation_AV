import os
import threading
import requests as req_lib
from app.core.firebase import db

BLYNK_BASE = 'https://blynk.cloud/external/api'

# ─── DYNAMIC DATA (Loaded from Firebase) ─────────────────────────────────────
_dynamic_lock = threading.Lock()
DYNAMIC_BOARDS = {}   # {tenant_id: {board_id: {name, board_type, blynk_token, ...}}}
DYNAMIC_ROOMS = {}    # {tenant_id: {room_id: {name, icon, order}}}
DYNAMIC_DEVICES = {}  # {tenant_id: {device_key: {name, room_name, board_id, pin, icon, type, ...}}}
DYNAMIC_ROOMS_LIST = {}  # {tenant_id: [Ordered list of room names for templates]}

# Auto-icon mapping for device types
DEVICE_TYPE_ICONS = {
    'fan': 'bi-wind', 'light': 'bi-lightbulb', 'tv': 'bi-tv',
    'ac': 'bi-thermometer-snow', 'geyser': 'bi-droplet-fill',
    'wifi': 'bi-wifi', 'switch': 'bi-toggle-on', 'other': 'bi-plug'
}

ALL_VIRTUAL_PINS = [f'V{i}' for i in range(32)]  # V0-V31 available on Blynk

# ─── SEED DATA (for first-boot Firebase migration) ───────────────────────────
SEED_BOARDS = {
    'esp8266_board': {
        'name': 'ESP8266 Board', 'board_type': 'esp8266',
        'blynk_template_id': 'TMPL3wjTF3gGK', 'blynk_template_name': 'BrightHaven',
        'blynk_token': os.getenv('BLYNK_TOKEN_ESP8266', 'PMgqRecE-oaYV9i_Hqxb8q8kSEemXqRO'),
        'mqtt_topic_prefix': 'brighthaven/relay/', 'wifi_ssid': 'MK',
        'status': 'unknown', 'last_seen': None, 'ip_address': '', 'rssi': 0,
    },
    'esp32_board': {
        'name': 'ESP32 Board', 'board_type': 'esp32',
        'blynk_template_id': 'TMPL3n_dCuyOY', 'blynk_template_name': 'BrightHaven1',
        'blynk_token': os.getenv('BLYNK_TOKEN_ESP32', '_o11JtMRBfA3QCLcvdpw7YpHKWGpBIcp'),
        'mqtt_topic_prefix': 'brighthaven1/relay/', 'wifi_ssid': 'MK',
        'status': 'unknown', 'last_seen': None, 'ip_address': '', 'rssi': 0,
    },
}

SEED_ROOMS = [
    {'name': 'Main Room', 'icon': 'bi-tv', 'order': 0},
    {'name': 'Bedroom 1', 'icon': 'bi-moon-stars', 'order': 1},
]

SEED_DEVICES = {
    'main_fan':    {'pin': 'V0', 'room_name': 'Main Room',  'name': 'Ceiling Fan',     'icon': 'bi-wind',             'device_type': 'fan',    'board_id': 'esp8266_board', 'type': 'blynk'},
    'main_light':  {'pin': 'V1', 'room_name': 'Main Room',  'name': 'Main Light',      'icon': 'bi-lightbulb',        'device_type': 'light',  'board_id': 'esp8266_board', 'type': 'blynk'},
    'main_tv':     {'pin': 'V2', 'room_name': 'Main Room',  'name': 'Television',      'icon': 'bi-tv',              'device_type': 'tv',     'board_id': 'esp8266_board', 'type': 'blynk'},
    'main_wifi':   {'pin': 'V3', 'room_name': 'Main Room',  'name': 'WiFi Router',     'icon': 'bi-wifi',             'device_type': 'wifi',   'board_id': 'esp8266_board', 'type': 'blynk'},
    'bed1_fan':    {'pin': 'V4', 'room_name': 'Bedroom 1',  'name': 'Fan',             'icon': 'bi-wind',             'device_type': 'fan',    'board_id': 'esp8266_board', 'type': 'blynk'},
    'bed1_light':  {'pin': 'V5', 'room_name': 'Bedroom 1',  'name': 'Light',           'icon': 'bi-lightbulb',        'device_type': 'light',  'board_id': 'esp8266_board', 'type': 'blynk'},
    'bed1_ac':     {'pin': 'V6', 'room_name': 'Bedroom 1',  'name': 'Air Conditioner', 'icon': 'bi-thermometer-snow', 'device_type': 'ac',     'board_id': 'esp8266_board', 'type': 'blynk'},
    'bed1_tv':     {'pin': 'V7', 'room_name': 'Bedroom 1',  'name': 'TV',              'icon': 'bi-tv',              'device_type': 'tv',     'board_id': 'esp8266_board', 'type': 'blynk'},
    'bed1_geyser': {'pin': 'V8', 'room_name': 'Bedroom 1',  'name': 'Water Geyser',    'icon': 'bi-droplet-fill',     'device_type': 'geyser', 'board_id': 'esp8266_board', 'type': 'blynk'},
    'esp32_main_fan':   {'pin': 'V0', 'room_name': 'Main Room', 'name': 'Main Room Fan (ESP32)',   'icon': 'bi-wind',             'device_type': 'fan',    'board_id': 'esp32_board', 'type': 'blynk'},
    'esp32_main_light': {'pin': 'V1', 'room_name': 'Main Room', 'name': 'Main Room Light (ESP32)', 'icon': 'bi-lightbulb',        'device_type': 'light',  'board_id': 'esp32_board', 'type': 'blynk'},
    'esp32_main_tv':    {'pin': 'V2', 'room_name': 'Main Room', 'name': 'Main Room TV (ESP32)',    'icon': 'bi-tv',              'device_type': 'tv',     'board_id': 'esp32_board', 'type': 'blynk'},
    'esp32_main_wifi':  {'pin': 'V3', 'room_name': 'Main Room', 'name': 'Main Room WiFi (ESP32)',  'icon': 'bi-wifi',             'device_type': 'wifi',   'board_id': 'esp32_board', 'type': 'blynk'},
    'esp32_bed1_fan':   {'pin': 'V4', 'room_name': 'Bedroom 1', 'name': 'Bedroom1 Fan (ESP32)',    'icon': 'bi-wind',             'device_type': 'fan',    'board_id': 'esp32_board', 'type': 'blynk'},
    'esp32_bed1_light': {'pin': 'V5', 'room_name': 'Bedroom 1', 'name': 'Bedroom1 Light (ESP32)', 'icon': 'bi-lightbulb',        'device_type': 'light',  'board_id': 'esp32_board', 'type': 'blynk'},
    'esp32_bed1_ac':    {'pin': 'V6', 'room_name': 'Bedroom 1', 'name': 'Bedroom1 AC (ESP32)',     'icon': 'bi-thermometer-snow', 'device_type': 'ac',     'board_id': 'esp32_board', 'type': 'blynk'},
    'esp32_bed1_tv':    {'pin': 'V7', 'room_name': 'Bedroom 1', 'name': 'Bedroom1 TV (ESP32)',     'icon': 'bi-tv',              'device_type': 'tv',     'board_id': 'esp32_board', 'type': 'blynk'},
    'esp32_bed1_geyser':{'pin': 'V8', 'room_name': 'Bedroom 1', 'name': 'Bedroom1 Geyser (ESP32)','icon': 'bi-droplet-fill',     'device_type': 'geyser', 'board_id': 'esp32_board', 'type': 'blynk'},
}

def load_dynamic_data():
    """Load boards, rooms, devices from Firebase into memory, partitioned by tenant_id"""
    global DYNAMIC_BOARDS, DYNAMIC_ROOMS, DYNAMIC_DEVICES, DYNAMIC_ROOMS_LIST
    try:
        boards = {}
        for doc in db.collection('boards').get():
            d = doc.to_dict()
            if not d.get('_init'):
                tid = d.get('tenant_id', 'tenant_default_001')
                if tid not in boards: boards[tid] = {}
                boards[tid][doc.id] = d
        
        rooms = {}
        for doc in db.collection('rooms').order_by('order').get():
            d = doc.to_dict()
            if not d.get('_init'):
                tid = d.get('tenant_id', 'tenant_default_001')
                if tid not in rooms: rooms[tid] = {}
                rooms[tid][doc.id] = d
        
        devices = {}
        for doc in db.collection('devices').get():
            d = doc.to_dict()
            if not d.get('_init') and d.get('pin'):
                tid = d.get('tenant_id', 'tenant_default_001')
                key = d.get('key', doc.id)
                board = boards.get(tid, {}).get(d.get('board_id', ''), {})
                if tid not in devices: devices[tid] = {}
                devices[tid][key] = {
                    'pin': d.get('pin', 'V0'),
                    'room': d.get('room_name', ''),
                    'name': d.get('name', 'Device'),
                    'icon': d.get('icon', 'bi-plug'),
                    'type': d.get('type', 'blynk'),
                    'board': board.get('board_type', 'esp8266'),
                    'board_id': d.get('board_id', ''),
                    'device_type': d.get('device_type', 'switch'),
                    'doc_id': doc.id,
                }
        
        rooms_list = {}
        for tid, r_dict in rooms.items():
            rooms_list[tid] = [r['name'] for r in sorted(r_dict.values(), key=lambda x: x.get('order', 99))]

        with _dynamic_lock:
            DYNAMIC_BOARDS = boards
            DYNAMIC_ROOMS = rooms
            DYNAMIC_DEVICES = devices
            DYNAMIC_ROOMS_LIST = rooms_list
        print(f"[Dynamic] Loaded data for {len(boards)} tenants")
    except Exception as e:
        print(f"[Dynamic] Load error: {e}")

def get_active_devices(tenant_id=None):
    """Return current device dict for tenant"""
    if not tenant_id:
        from flask import g
        tenant_id = getattr(g, 'tenant_id', 'tenant_default_001')
    with _dynamic_lock:
        if tenant_id in DYNAMIC_DEVICES:
            return dict(DYNAMIC_DEVICES[tenant_id])
    return {k: {**v, 'room': v.get('room_name', ''), 'board': 'esp8266'} for k, v in SEED_DEVICES.items()}

def get_active_rooms(tenant_id=None):
    """Return current room list for tenant"""
    if not tenant_id:
        from flask import g
        tenant_id = getattr(g, 'tenant_id', 'tenant_default_001')
    with _dynamic_lock:
        if tenant_id in DYNAMIC_ROOMS_LIST:
            return list(DYNAMIC_ROOMS_LIST[tenant_id])
    return [r['name'] for r in SEED_ROOMS]

def get_board_token(board_id, tenant_id=None):
    """Get Blynk token for a board"""
    if not tenant_id:
        from flask import g
        try: tenant_id = getattr(g, 'tenant_id', 'tenant_default_001')
        except: tenant_id = 'tenant_default_001'
    with _dynamic_lock:
        board = DYNAMIC_BOARDS.get(tenant_id, {}).get(board_id, {})
    return board.get('blynk_token', '')

def get_free_pins(board_id, tenant_id=None):
    """Get available virtual pins for a board"""
    used = set()
    devices = get_active_devices(tenant_id)
    for dev in devices.values():
        if dev.get('board_id') == board_id:
            used.add(dev.get('pin', ''))
    return [p for p in ALL_VIRTUAL_PINS[:9] if p not in used]

def check_board_online(board_id):
    """Check if a board is online via Blynk isHardwareConnected API"""
    token = get_board_token(board_id)
    if not token:
        return False
    try:
        r = req_lib.get(f"{BLYNK_BASE}/isHardwareConnected", params={'token': token}, timeout=3)
        return r.status_code == 200 and r.json() == True
    except Exception:
        return False
