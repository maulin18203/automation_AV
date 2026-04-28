import threading
import time
import requests as req_lib
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.core.dynamic_data import get_active_devices, get_board_token, DYNAMIC_BOARDS, _dynamic_lock, BLYNK_BASE

# ─── RASPBERRY PI GPIO SETUP ─────────────────────────────────────────────────
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BOARD)
    GPIO.setwarnings(False)
    GPIO_AVAILABLE = True
except ImportError:
    print("[GPIO] RPi.GPIO not available — GPIO features disabled")
    GPIO_AVAILABLE = False

# ─── GPIO CONTROLLER ─────────────────────────────────────────────────────────
class GPIOController:
    """Active-Low relay controller for Raspberry Pi GPIO pins"""

    def __init__(self):
        self._states = {}
        self._lock = threading.Lock()

    def init_pins(self):
        if not GPIO_AVAILABLE:
            return
        devices = get_active_devices()
        for dev_id, dev in devices.items():
            if dev.get('type') == 'gpio':
                pin = dev['pin']
                try:
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
                    print(f"[GPIO] Pin {pin} ({dev['name']}) initialized — OFF")
                except Exception as e:
                    print(f"[GPIO] Pin {pin} init error: {e}")

    def set_pin(self, pin, state):
        if not GPIO_AVAILABLE:
            return False
        try:
            with self._lock:
                GPIO.output(pin, GPIO.LOW if state else GPIO.HIGH)
                self._states[pin] = state
                return True
        except Exception as e:
            print(f"[GPIO] Pin {pin} error: {e}")
            return False

    def get_pin(self, pin):
        if not GPIO_AVAILABLE:
            return False
        try:
            return GPIO.input(pin) == GPIO.LOW
        except Exception:
            return self._states.get(pin, False)

    def shutdown_all(self):
        if not GPIO_AVAILABLE:
            return
        devices = get_active_devices()
        with self._lock:
            for dev_id, dev in devices.items():
                if dev.get('type') == 'gpio':
                    try:
                        GPIO.output(dev['pin'], GPIO.HIGH)
                        self._states[dev['pin']] = False
                    except Exception:
                        pass

gpio_ctrl = GPIOController()

# ─── BLYNK HTTP HELPERS (Dual Token) ─────────────────────────────────────────
_http = req_lib.Session()

def blynk_token_for_device(dev_key):
    """Return the correct Blynk auth token for the device's board"""
    devices = get_active_devices()
    dev = devices.get(dev_key, {})
    board_id = dev.get('board_id', '')
    if board_id:
        token = get_board_token(board_id)
        if token:
            return token
    # Fallback: check board type
    with _dynamic_lock:
        for bid, b in DYNAMIC_BOARDS.items():
            if b.get('board_type') == dev.get('board', 'esp8266'):
                return b.get('blynk_token', '')
    return ''

def blynk_get(pin, token=None):
    """Read a virtual pin from Blynk Cloud using the given token"""
    if not token:
        return False
    try:
        r = _http.get(f"{BLYNK_BASE}/get", params={'token': token, 'pin': pin}, timeout=3)
        return r.status_code == 200 and r.json()[0] == '1'
    except Exception:
        return False

def blynk_set(pin, val, token=None):
    """Write a virtual pin to Blynk Cloud using the given token"""
    if not token:
        return False
    try:
        r = _http.get(f"{BLYNK_BASE}/update", params={'token': token, pin: val}, timeout=3)
        return r.status_code == 200
    except Exception:
        return False

# ─── DEVICE STATE CACHE ──────────────────────────────────────────────────────
class DeviceCache:
    """Unified device state cache — combines MQTT, Blynk, and GPIO states"""

    def __init__(self):
        self._states = {}
        self._lock = threading.Lock()
        self._last_refresh = 0
        self.CACHE_TTL = 5

    def get_all(self):
        devices = get_active_devices()
        with self._lock:
            states = dict(self._states)
            for dev_id, dev in devices.items():
                if dev.get('type') == 'gpio':
                    states[dev_id] = gpio_ctrl.get_pin(dev['pin'])
                elif dev_id not in states:
                    states[dev_id] = False
            return states

    def get(self, device_key):
        devices = get_active_devices()
        dev = devices.get(device_key)
        if dev and dev.get('type') == 'gpio':
            return gpio_ctrl.get_pin(dev['pin'])
        with self._lock:
            return self._states.get(device_key, False)

    def set(self, device_key, state):
        devices = get_active_devices()
        dev = devices.get(device_key)
        if dev and dev.get('type') == 'gpio':
            gpio_ctrl.set_pin(dev['pin'], state)
        with self._lock:
            self._states[device_key] = state

    def refresh_all(self):
        def _fetch_one(item):
            key, dev = item
            if dev.get('type') == 'gpio':
                return key, gpio_ctrl.get_pin(dev['pin'])
            # Select correct Blynk token based on board
            token = blynk_token_for_device(key)
            try:
                r = _http.get(f"{BLYNK_BASE}/get", params={'token': token, 'pin': dev['pin']}, timeout=3)
                return key, (r.status_code == 200 and r.json()[0] == '1')
            except Exception:
                return key, False

        devices = get_active_devices()
        blynk_items = [(k, v) for k, v in devices.items() if v.get('type') != 'gpio']
        results = {}
        with ThreadPoolExecutor(max_workers=24) as ex:
            futures = {ex.submit(_fetch_one, item): item for item in blynk_items}
            try:
                for f in as_completed(futures, timeout=5):
                    try:
                        k, v = f.result()
                        results[k] = v
                    except Exception:
                        pass
            except TimeoutError:
                pass

        with self._lock:
            self._states.update(results)
            self._last_refresh = time.time()

    def start_background_refresh(self):
        def _loop():
            while True:
                try:
                    self.refresh_all()
                except Exception:
                    pass
                time.sleep(self.CACHE_TTL)
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        print("[Cache] Background Blynk refresh started (every 5s)")

cache = DeviceCache()
