"""Unit tests for middleware._publish_locations — verify MQTT topic + payload shape."""
import json
from unittest.mock import MagicMock


def test_publish_locations_uses_per_device_topic_and_payload(monkeypatch):
    import middleware

    fake_client = MagicMock()
    monkeypatch.setattr(middleware, "_mqtt_client", fake_client)
    monkeypatch.setattr(middleware, "MQTT_TOPIC", "findmy/devices")

    data = [
        {"device_name": "Tracker-A", "lat": 51.05, "lon": 3.71,
         "altitude": 10.0, "accuracy": 5.0, "time": "2026-05-21T10:00:00+00:00"},
        {"device_name": "Tracker-B", "lat": 50.85, "lon": 4.35,
         "altitude": 20.0, "accuracy": 9.0, "time": "2026-05-21T10:00:01+00:00"},
    ]
    middleware._publish_locations(data)

    assert fake_client.publish.call_count == 2

    first_call = fake_client.publish.call_args_list[0]
    assert first_call.args[0] == "findmy/devices/Tracker-A/location"
    payload = json.loads(first_call.args[1])
    assert payload["device_name"] == "Tracker-A"
    assert payload["lat"] == 51.05
    assert payload["lon"] == 3.71
    assert first_call.kwargs["qos"] == 1
    assert first_call.kwargs["retain"] is True


def test_publish_locations_skips_missing_coordinates(monkeypatch):
    import middleware

    fake_client = MagicMock()
    monkeypatch.setattr(middleware, "_mqtt_client", fake_client)

    data = [
        {"device_name": "Semantic-Only", "lat": None, "lon": None,
         "altitude": None, "accuracy": None, "time": "t"},
        {"device_name": "Has-Coords", "lat": 1.0, "lon": 2.0,
         "altitude": 0.0, "accuracy": 0.0, "time": "t"},
    ]
    middleware._publish_locations(data)

    assert fake_client.publish.call_count == 1
    assert "Has-Coords" in fake_client.publish.call_args.args[0]


def test_publish_locations_is_noop_without_mqtt_client(monkeypatch):
    import middleware

    monkeypatch.setattr(middleware, "_mqtt_client", None)
    middleware._publish_locations([
        {"device_name": "x", "lat": 1.0, "lon": 2.0,
         "altitude": 0.0, "accuracy": 0.0, "time": "t"}
    ])
