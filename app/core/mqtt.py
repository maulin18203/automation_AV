import os
from dotenv import load_dotenv
from app.core.mqtt_bridge import MQTTBridge

load_dotenv()

mqtt_bridge = MQTTBridge(
    broker=os.getenv('MQTT_BROKER', 'broker.emqx.io'),
    port=int(os.getenv('MQTT_PORT', '8883')),
    username=os.getenv('MQTT_USERNAME', ''),
    password=os.getenv('MQTT_PASSWORD', ''),
    use_tls=os.getenv('MQTT_USE_TLS', 'true').lower() == 'true'
)
