import sys
sys.path.insert(0, '.')

import os
import time
import threading
import argparse

import requests
from flask import Flask, jsonify

from location_fetcher import fetch_all_locations

app = Flask(__name__)

PUSH_URL = os.environ.get("PUSH_URL", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 300))
PORT = int(os.environ.get("PORT", 5500))

_cache: list = []
_cache_lock = threading.Lock()
_last_poll: float = 0.0


def _push_to_webhook(data: list) -> None:
    if not PUSH_URL:
        return
    try:
        resp = requests.post(PUSH_URL, json=data, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[push] webhook error: {e}")


def _push_to_supabase(data: list) -> None:
    supabase_url = os.environ.get("SUPABASE_URL")
    if not supabase_url:
        return
    try:
        from supabase import create_client

        key = os.environ["SUPABASE_KEY"]
        client = create_client(supabase_url, key)

        rows = [
            {
                "device_name": d["device_name"],
                "lat":         d["lat"],
                "lon":         d["lon"],
                "altitude":    d.get("altitude") or 0.0,
                "accuracy":    d.get("accuracy") or 0.0,
            }
            for d in data if d["lat"] is not None and d["lon"] is not None
        ]
        if rows:
            client.table("device_locations").insert(rows).execute()
            print(f"[supabase] inserted {len(rows)} row(s)")
    except ImportError:
        print("[supabase] supabase-py not installed — skipping")
    except Exception as e:
        print(f"[supabase] error: {e}")


def polling_loop() -> None:
    global _cache, _last_poll
    while True:
        try:
            print("[poll] fetching locations...")
            data = fetch_all_locations(timeout_per_device=30)
            with _cache_lock:
                _cache = data
                _last_poll = time.time()
            print(f"[poll] got {len(data)} location record(s)")
            _push_to_webhook(data)
            _push_to_supabase(data)
        except Exception as e:
            print(f"[poll] error: {e}")
        time.sleep(POLL_INTERVAL)


@app.route("/devices")
def devices():
    with _cache_lock:
        return jsonify({
            "last_poll": _last_poll,
            "devices": _cache,
        })


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--push-url",  default=PUSH_URL)
    parser.add_argument("--interval",  type=int, default=POLL_INTERVAL)
    parser.add_argument("--port",      type=int, default=PORT)
    args = parser.parse_args()

    PUSH_URL      = args.push_url
    POLL_INTERVAL = args.interval
    PORT          = args.port

    t = threading.Thread(target=polling_loop, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=PORT)
