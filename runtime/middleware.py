import os
import json
import time
import threading
import argparse

import paho.mqtt.client as mqtt
from flask import Flask, jsonify

from location_fetcher import fetch_all_locations, fetch_device_list
from settings import load_runtime_settings

app = Flask(__name__)

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 300))
PORT = int(os.environ.get("PORT", 5500))

MQTT_HOST     = os.environ.get("MQTT_HOST", "")
MQTT_PORT     = int(os.environ.get("MQTT_PORT", 8883))
MQTT_USER     = os.environ.get("MQTT_USER", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
MQTT_TOPIC    = os.environ.get("MQTT_TOPIC", "findmy/devices")

_cache: list = []
_cache_lock = threading.Lock()
_last_poll: float = 0.0

_mqtt_client: mqtt.Client | None = None
_polling_thread: threading.Thread | None = None
_start_lock = threading.Lock()


def _connect_mqtt() -> mqtt.Client | None:
    if not MQTT_HOST:
        print("[mqtt] MQTT_HOST not set — skipping")
        return None
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.tls_set()
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    print(f"[mqtt] connected to {MQTT_HOST}:{MQTT_PORT}")
    return client


def _publish_locations(data: list) -> None:
    if _mqtt_client is None:
        return
    for device in data:
        if device["lat"] is None or device["lon"] is None:
            continue
        payload = json.dumps({
            "device_name": device["device_name"],
            "lat":         device["lat"],
            "lon":         device["lon"],
            "altitude":    device.get("altitude") or 0.0,
            "accuracy":    device.get("accuracy") or 0.0,
            "time":        device.get("time"),
        })
        topic = f"{MQTT_TOPIC}/{device['device_name']}/location"
        _mqtt_client.publish(topic, payload, qos=1, retain=True)
    print(f"[mqtt] published {len(data)} device(s)")


def polling_loop() -> None:
    global _cache, _last_poll
    while True:
        # Re-read settings each cycle so portal edits apply without a restart.
        cfg = load_runtime_settings()
        try:
            print(f"[poll] fetching locations... (interval={cfg['poll_interval']}s, "
                  f"batch={cfg['location_batch_size']}, delay={cfg['location_batch_delay']}s, "
                  f"timeout={cfg['location_timeout']}s)")
            data = fetch_all_locations(
                timeout_per_device=cfg["location_timeout"],
                batch_size=cfg["location_batch_size"],
                batch_delay=cfg["location_batch_delay"],
            )
            with _cache_lock:
                _cache = data
                _last_poll = time.time()
            print(f"[poll] got {len(data)} location record(s)")
            _publish_locations(data)
        except Exception as e:
            print(f"[poll] error: {e}")
        time.sleep(cfg["poll_interval"])


def _start_background_workers() -> None:
    """Idempotent: start MQTT client + polling thread on first call.
    Safe to call from gunicorn worker boot and from __main__."""
    global _mqtt_client, _polling_thread
    with _start_lock:
        if _polling_thread is not None and _polling_thread.is_alive():
            return
        if _mqtt_client is None:
            _mqtt_client = _connect_mqtt()
        _polling_thread = threading.Thread(target=polling_loop, daemon=True)
        _polling_thread.start()


if os.environ.get("MIDDLEWARE_AUTOSTART", "1") == "1":
    _start_background_workers()


@app.route("/devices")
def devices():
    with _cache_lock:
        return jsonify({
            "last_poll": _last_poll,
            "devices": _cache,
        })


@app.route("/devicelist")
def devicelist():
    try:
        devices = fetch_device_list()
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({
        "devices": [{"device_name": name, "canonic_id": cid} for name, cid in devices],
    })


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL)
    parser.add_argument("--port",     type=int, default=PORT)
    args = parser.parse_args()

    POLL_INTERVAL = args.interval
    PORT          = args.port

    # The polling loop reads the interval from settings (env default when
    # Supabase is unset); surface --interval there so local runs honour it.
    os.environ["POLL_INTERVAL"] = str(args.interval)

    # Always start when invoked directly via `python runtime/middleware.py`
    _start_background_workers()

    app.run(host="0.0.0.0", port=PORT)
