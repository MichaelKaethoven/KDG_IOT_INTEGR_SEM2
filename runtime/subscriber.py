"""
Subscribes to MQTT device location topics and persists each message to Supabase.
Topic pattern: findmy/devices/+/location
"""

import json
import os
import sys

import paho.mqtt.client as mqtt

MQTT_HOST     = os.environ.get("MQTT_HOST", "")
MQTT_PORT     = int(os.environ.get("MQTT_PORT", 8883))
MQTT_USER     = os.environ.get("MQTT_USER", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
MQTT_TOPIC    = os.environ.get("MQTT_TOPIC", "findmy/devices")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

_supabase = None


def _get_supabase():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return None
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("[supabase] client initialised")
    return _supabase


def _upsert(payload: dict) -> None:
    client = _get_supabase()
    if client is None:
        print("[supabase] credentials not set — skipping")
        return
    row = {
        "device_name": payload["device_name"],
        "lat":         payload["lat"],
        "lon":         payload["lon"],
        "altitude":    payload.get("altitude") or 0.0,
        "accuracy":    payload.get("accuracy") or 0.0,
        "time":        payload.get("time"),
    }
    client.table("device_locations").upsert(row, on_conflict="device_name,time").execute()
    print(f"[supabase] upserted {payload['device_name']}")


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        subscribe_topic = f"{MQTT_TOPIC}/+/location"
        client.subscribe(subscribe_topic, qos=1)
        print(f"[mqtt] subscribed to {subscribe_topic}")
    else:
        print(f"[mqtt] connection failed: {reason_code}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        print(f"[mqtt] received: {payload.get('device_name')} @ {payload.get('lat')},{payload.get('lon')}")
        _upsert(payload)
    except Exception as e:
        print(f"[mqtt] error processing message: {e}")


if __name__ == "__main__":
    if not MQTT_HOST:
        print("[mqtt] MQTT_HOST not set — exiting")
        sys.exit(1)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.tls_set()
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[mqtt] connecting to {MQTT_HOST}:{MQTT_PORT}")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()
