"""
╔══════════════════════════════════════════════════════════════╗
║          BrightHaven — MQTT Bridge Module                   ║
║  Connects Flask backend to EMQX/HiveMQ MQTT broker.        ║
║  Handles device status, heartbeats, command publishing.     ║
╚══════════════════════════════════════════════════════════════╝
"""

import json
import ssl
import time
import threading
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    print("[MQTT] paho-mqtt not installed — MQTT features disabled")
    MQTT_AVAILABLE = False


class MQTTBridge:
    """
    Bridges MQTT broker ↔ Flask app.
    - Subscribes to device/+/status and device/+/heartbeat
    - Publishes commands to device/{id}/command
    - Maintains device state cache
    - Emits events to SSE subscribers
    """

    def __init__(self, broker, port=8883, username=None, password=None, use_tls=True):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls

        self._connected = False
        self._client = None
        self._lock = threading.Lock()

        # Device state cache  {deviceId: {relay: int, state: str, uptime: int, rssi: int, online: bool, lastSeen: datetime}}
        self._device_states = {}

        # SSE subscribers — list of queues
        self._sse_queues = []
        self._sse_lock = threading.Lock()

        # Callbacks for Firestore updates (set by app.py)
        self.on_device_status = None    # Called when device publishes status
        self.on_device_heartbeat = None # Called when device publishes heartbeat
        self.on_device_offline = None   # Called when device goes offline

        if MQTT_AVAILABLE:
            self._setup_client()

    def _setup_client(self):
        """Initialize MQTT client with callbacks"""
        self._client = mqtt.Client(
            client_id=f"brighthaven_cloud_{int(time.time())}",
            protocol=mqtt.MQTTv311
        )

        if self.username:
            self._client.username_pw_set(self.username, self.password)

        if self.use_tls:
            self._client.tls_set(
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS
            )
            self._client.tls_insecure_set(False)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # Last Will — cloud bridge offline notification
        self._client.will_set(
            "system/cloud/status",
            json.dumps({"status": "offline", "timestamp": int(time.time())}),
            qos=1, retain=True
        )

    def _on_connect(self, client, userdata, flags, rc):
        """Called when connected to broker"""
        if rc == 0:
            self._connected = True
            print(f"[MQTT] ✅ Connected to {self.broker}:{self.port}")

            # Subscribe to all device topics
            client.subscribe("device/+/status", qos=1)
            client.subscribe("device/+/heartbeat", qos=0)
            print("[MQTT] Subscribed to device/+/status and device/+/heartbeat")

            # Announce cloud bridge online
            client.publish(
                "system/cloud/status",
                json.dumps({"status": "online", "timestamp": int(time.time())}),
                qos=1, retain=True
            )
        else:
            print(f"[MQTT] ❌ Connection failed with code {rc}")
            self._connected = False

    def _on_disconnect(self, client, userdata, rc):
        """Called when disconnected from broker"""
        self._connected = False
        if rc != 0:
            print(f"[MQTT] ⚠️ Unexpected disconnect (rc={rc}). Will auto-reconnect...")

    def _on_message(self, client, userdata, msg):
        """Called when a message is received on subscribed topics"""
        try:
            topic_parts = msg.topic.split("/")
            if len(topic_parts) < 3:
                return

            device_id = topic_parts[1]
            msg_type = topic_parts[2]
            payload = json.loads(msg.payload.decode("utf-8"))

            if msg_type == "status":
                self._handle_status(device_id, payload)
            elif msg_type == "heartbeat":
                self._handle_heartbeat(device_id, payload)

        except json.JSONDecodeError:
            print(f"[MQTT] Invalid JSON on {msg.topic}")
        except Exception as e:
            print(f"[MQTT] Error processing message: {e}")

    def _handle_status(self, device_id, payload):
        """Process device status update"""
        with self._lock:
            if device_id not in self._device_states:
                self._device_states[device_id] = {}

            self._device_states[device_id].update({
                "relay": payload.get("relay"),
                "state": payload.get("state", "OFF"),
                "uptime": payload.get("uptime", 0),
                "rssi": payload.get("rssi", 0),
                "online": True,
                "lastSeen": datetime.now()
            })

        # Emit SSE event
        self._emit_sse({
            "type": "device_status",
            "deviceId": device_id,
            "data": payload
        })

        # Callback to update Firestore
        if self.on_device_status:
            try:
                self.on_device_status(device_id, payload)
            except Exception as e:
                print(f"[MQTT] Firestore status callback error: {e}")

    def _handle_heartbeat(self, device_id, payload):
        """Process device heartbeat"""
        with self._lock:
            if device_id not in self._device_states:
                self._device_states[device_id] = {}

            self._device_states[device_id].update({
                "uptime": payload.get("uptime", 0),
                "rssi": payload.get("rssi", 0),
                "online": True,
                "lastSeen": datetime.now()
            })

        # Callback
        if self.on_device_heartbeat:
            try:
                self.on_device_heartbeat(device_id, payload)
            except Exception as e:
                print(f"[MQTT] Firestore heartbeat callback error: {e}")

    # ─── PUBLIC API ───────────────────────────────────────────────────────────

    def connect(self):
        """Connect to MQTT broker in background thread"""
        if not MQTT_AVAILABLE or not self._client:
            print("[MQTT] Client not available — running in offline mode")
            return False

        try:
            self._client.connect_async(self.broker, self.port, keepalive=60)
            self._client.loop_start()
            print(f"[MQTT] Connecting to {self.broker}:{self.port}...")
            return True
        except Exception as e:
            print(f"[MQTT] Connection error: {e}")
            return False

    def disconnect(self):
        """Gracefully disconnect from broker"""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            print("[MQTT] Disconnected")

    def publish_command(self, device_id, relay, state, timestamp=None):
        """
        Publish a command to a device.
        Topic: device/{deviceId}/command
        Payload: {"relay": 1, "state": "ON", "timestamp": 1710000000}
        """
        if not self._connected:
            print(f"[MQTT] Not connected — cannot publish to {device_id}")
            return False

        payload = {
            "relay": relay,
            "state": "ON" if state else "OFF",
            "timestamp": timestamp or int(time.time())
        }

        topic = f"device/{device_id}/command"
        result = self._client.publish(topic, json.dumps(payload), qos=1, retain=True)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            return True
        else:
            print(f"[MQTT] Publish failed to {topic}: rc={result.rc}")
            return False

    def publish_broadcast(self, home_id, command, timestamp=None):
        """
        Publish a broadcast command to all devices in a home.
        Topic: home/{homeId}/broadcast
        """
        if not self._connected:
            return False

        payload = {
            "command": command,
            "timestamp": timestamp or int(time.time())
        }

        topic = f"home/{home_id}/broadcast"
        result = self._client.publish(topic, json.dumps(payload), qos=1)
        return result.rc == mqtt.MQTT_ERR_SUCCESS

    def publish_ota(self, device_id, firmware_url, sha256):
        """
        Push OTA firmware update to a device.
        Topic: device/{deviceId}/ota
        """
        if not self._connected:
            return False

        payload = {
            "url": firmware_url,
            "sha256": sha256,
            "timestamp": int(time.time())
        }

        topic = f"device/{device_id}/ota"
        result = self._client.publish(topic, json.dumps(payload), qos=1)
        return result.rc == mqtt.MQTT_ERR_SUCCESS

    def get_device_state(self, device_id):
        """Get cached state for a device"""
        with self._lock:
            return self._device_states.get(device_id, {})

    def get_all_states(self):
        """Get all cached device states"""
        with self._lock:
            return dict(self._device_states)

    def is_connected(self):
        """Check if MQTT broker connection is active"""
        return self._connected

    # ─── SSE (Server-Sent Events) ─────────────────────────────────────────────

    def subscribe_sse(self):
        """Register a new SSE subscriber. Returns a queue-like generator."""
        import queue
        q = queue.Queue(maxsize=50)
        with self._sse_lock:
            self._sse_queues.append(q)
        return q

    def unsubscribe_sse(self, q):
        """Remove an SSE subscriber"""
        with self._sse_lock:
            if q in self._sse_queues:
                self._sse_queues.remove(q)

    def _emit_sse(self, event_data):
        """Push event to all SSE subscribers"""
        dead = []
        with self._sse_lock:
            for q in self._sse_queues:
                try:
                    q.put_nowait(event_data)
                except Exception:
                    dead.append(q)
            for q in dead:
                self._sse_queues.remove(q)

    # ─── HEARTBEAT WATCHDOG ───────────────────────────────────────────────────

    def start_watchdog(self, timeout_seconds=45):
        """Background thread that marks devices offline if no heartbeat received"""
        def _watchdog():
            while True:
                try:
                    now = datetime.now()
                    with self._lock:
                        for device_id, state in self._device_states.items():
                            last_seen = state.get("lastSeen")
                            if last_seen and state.get("online"):
                                delta = (now - last_seen).total_seconds()
                                if delta > timeout_seconds:
                                    state["online"] = False
                                    print(f"[MQTT] ⚠️ Device {device_id} marked OFFLINE (no heartbeat for {int(delta)}s)")

                                    # Emit offline event
                                    self._emit_sse({
                                        "type": "device_offline",
                                        "deviceId": device_id
                                    })

                                    # Callback
                                    if self.on_device_offline:
                                        try:
                                            self.on_device_offline(device_id)
                                        except Exception:
                                            pass
                except Exception as e:
                    print(f"[MQTT Watchdog] Error: {e}")

                time.sleep(15)  # Check every 15 seconds

        t = threading.Thread(target=_watchdog, daemon=True)
        t.start()
        print("[MQTT] Heartbeat watchdog started (timeout: 45s)")
