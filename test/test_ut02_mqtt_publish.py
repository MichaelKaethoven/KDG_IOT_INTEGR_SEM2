"""UT-02 — Unit Test: MQTT publish door middleware.py.

Maps to Testplan SC-LOC-01, sheet "UT-02 MQTT publish". Exercises
`middleware._publish_locations` with a mocked paho MQTT client (no broker).

| TC   | Scenario                                          | Verified here                       |
|------|---------------------------------------------------|-------------------------------------|
| TC-A | Geldige locatie → bericht op correct topic        | test_tc_a_valid_location_published  |
| TC-B | Lege lijst → geen publicatie, log-entry           | test_tc_b_empty_list_no_publish     |
| TC-C | lat=None (semantisch) → geen crash, overgeslagen  | test_tc_c_semantic_location_no_crash|

Behaviour verified:
- TC-B: an empty list produces no publish call and logs "published 0 device(s)".
- TC-C: a device with lat/lon == None is skipped (no MQTT message, no crash).
"""
import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def middleware_with_fake_mqtt(monkeypatch):
    import middleware

    fake_client = MagicMock()
    monkeypatch.setattr(middleware, "_mqtt_client", fake_client)
    monkeypatch.setattr(middleware, "MQTT_TOPIC", "findmy/devices")
    return middleware, fake_client


# ---------------------------------------------------------------------------
# TC-A — Geldige locatie → bericht gepubliceerd op correct MQTT-topic
# ---------------------------------------------------------------------------
def test_tc_a_valid_location_published(middleware_with_fake_mqtt):
    middleware, fake_client = middleware_with_fake_mqtt

    data = [{
        "device_name": "TRK-007", "lat": 51.2194, "lon": 4.4025,
        "altitude": 12.0, "accuracy": 8.0, "time": "2025-05-28T10:00:00Z",
    }]
    middleware._publish_locations(data)

    fake_client.publish.assert_called_once()
    call = fake_client.publish.call_args

    # Topic: findmy/devices/TRK-007/location
    assert call.args[0] == "findmy/devices/TRK-007/location"

    # Payload: JSON met device_name, lat, lon, altitude, accuracy, time.
    payload = json.loads(call.args[1])
    assert payload["device_name"] == "TRK-007"
    assert payload["lat"] == 51.2194
    assert payload["lon"] == 4.4025
    assert payload["time"] == "2025-05-28T10:00:00Z"

    # QoS 1 + retain so a late dashboard still gets the last known position.
    assert call.kwargs["qos"] == 1
    assert call.kwargs["retain"] is True


# ---------------------------------------------------------------------------
# TC-B — Lege lijst → geen publicatie, log-entry aanwezig
# ---------------------------------------------------------------------------
def test_tc_b_empty_list_no_publish(middleware_with_fake_mqtt, capsys):
    middleware, fake_client = middleware_with_fake_mqtt

    middleware._publish_locations([])

    fake_client.publish.assert_not_called()              # geen MQTT-bericht
    out = capsys.readouterr().out
    assert "published 0 device" in out.lower()           # log-entry aanwezig


# ---------------------------------------------------------------------------
# TC-C — lat=None (semantische locatie) → geen crash, device overgeslagen
# ---------------------------------------------------------------------------
def test_tc_c_semantic_location_no_crash(middleware_with_fake_mqtt):
    middleware, fake_client = middleware_with_fake_mqtt

    data = [
        # semantic-only fix: no coordinates → must be skipped, must not crash
        {"device_name": "TRK-007", "lat": None, "lon": None,
         "altitude": None, "accuracy": None, "time": "2025-05-28T10:00:00Z"},
        # a real fix in the same batch still gets published
        {"device_name": "TRK-008", "lat": 51.0, "lon": 4.0,
         "altitude": 0.0, "accuracy": 0.0, "time": "2025-05-28T10:00:01Z"},
    ]
    middleware._publish_locations(data)

    # Only the device with coordinates is published; the semantic one is skipped.
    assert fake_client.publish.call_count == 1
    assert "TRK-008" in fake_client.publish.call_args.args[0]
