"""Shared pytest configuration.

- Disables the middleware module's auto-start side effect, so importing
  `middleware` in tests does not spin up a real polling thread or MQTT client.
- Sets placeholder env vars consumed at module import time by the runtime modules.
"""
import os

os.environ.setdefault("MIDDLEWARE_AUTOSTART", "0")
os.environ.setdefault("MQTT_TOPIC", "findmy/devices")
os.environ.setdefault("MQTT_PORT", "8883")
