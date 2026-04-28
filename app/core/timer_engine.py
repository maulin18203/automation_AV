import threading
import time
from datetime import datetime
from google.cloud.firestore_v1.base_query import FieldFilter
from app.core.firebase import db
from app.core.dynamic_data import get_active_devices
from app.core.hardware import cache, blynk_set, blynk_token_for_device

class TimerEngine:
    """Background thread that executes device timers (auto ON/OFF after duration)"""

    def __init__(self):
        self._running = True

    def start(self):
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        print("[Timer] Timer engine started (checking every 30s)")

    def _loop(self):
        while self._running:
            try:
                self._check_timers()
            except Exception as e:
                print(f"[Timer] Error: {e}")
            time.sleep(30)

    def _check_timers(self):
        now = datetime.now()
        try:
            docs = db.collection('timers').where(filter=FieldFilter('status', '==', 'active')).get()
            for doc in docs:
                timer = doc.to_dict()
                end_time = timer.get('end_time')
                if end_time and end_time <= now:
                    self._execute_timer(doc.id, timer)
        except Exception as e:
            print(f"[Timer] Check error: {e}")

    def _execute_timer(self, timer_id, timer):
        device_key = timer.get('device_id', '')
        action = timer.get('action', 'off')
        state = 1 if action == 'on' else 0
        devices = get_active_devices()
        dev = devices.get(device_key)
        if dev:
            token = blynk_token_for_device(device_key)
            ok = blynk_set(dev['pin'], state, token=token)
            if ok:
                cache.set(device_key, bool(state))
                print(f"[Timer] Executed: {device_key} → {action.upper()}")
                # Log to Firebase
                db.collection('logs').add({
                    'username': 'Timer Engine', 'userId': 'system',
                    'action': f"TIMER {action.upper()}: {dev.get('name', device_key)}",
                    'deviceId': device_key, 'ip_address': 'localhost',
                    'timestamp': datetime.now()
                })
                # Update device state in Firebase
                try:
                    dev_docs = db.collection('devices').where(filter=FieldFilter('key', '==', device_key)).limit(1).get()
                    for d in dev_docs:
                        d.reference.update({'state': bool(state), 'last_toggled': datetime.now()})
                except Exception:
                    pass
        # Mark timer complete
        db.collection('timers').document(timer_id).update({
            'status': 'completed', 'completed_at': datetime.now()
        })

timer_engine = TimerEngine()
