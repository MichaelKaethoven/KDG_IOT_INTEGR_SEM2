"""UT-01 — Unit Test: Supabase upsert & deduplicatie (subscriber.py).

Maps to Testplan SC-LOC-01, sheet "UT-01 Supabase upsert". Each test below
corresponds to one TC# from the plan and exercises the real message-handling
path (`subscriber.on_message` → `subscriber._upsert`) with a mocked Supabase
client, so no network/DB is touched.

| TC   | Scenario                                   | Verified here                         |
|------|--------------------------------------------|---------------------------------------|
| TC-A | Geldig bericht → rij aangemaakt            | test_tc_a_valid_message_upserts_row   |
| TC-B | Zelfde bericht opnieuw → geen duplicaat    | test_tc_b_repeat_message_dedup_contract |
| TC-C | Ongeldig JSON → fout gelogd, blijft draaien| test_tc_c_invalid_json_logged_survives|
| TC-D | Bericht zonder lat → graceful skip         | test_tc_d_missing_lat_graceful_skip   |

Payload schema: the contract between middleware.py and subscriber.py uses keys
{"device_name","lat","lon","altitude","accuracy","time"}.
"""
from unittest.mock import MagicMock

import pytest


class _FakeMsg:
    """Minimal stand-in for a paho MQTT message: only `.payload` (bytes) is read."""

    def __init__(self, raw: bytes | str):
        self.payload = raw.encode() if isinstance(raw, str) else raw


VALID_PAYLOAD = (
    '{"device_name":"TRK-007","lat":51.2194,"lon":4.4025,'
    '"altitude":12.0,"accuracy":8.0,"time":"2025-05-28T10:00:00Z"}'
)


@pytest.fixture
def subscriber_with_fake_db(monkeypatch):
    """Import subscriber and swap its Supabase client for a MagicMock."""
    import subscriber

    fake_client = MagicMock()
    monkeypatch.setattr(subscriber, "_get_supabase", lambda: fake_client)
    return subscriber, fake_client


# ---------------------------------------------------------------------------
# TC-A — Geldig bericht → één rij aangemaakt in device_locations
# ---------------------------------------------------------------------------
def test_tc_a_valid_message_upserts_row(subscriber_with_fake_db):
    subscriber, fake_client = subscriber_with_fake_db

    subscriber.on_message(None, None, _FakeMsg(VALID_PAYLOAD))

    # Exactly one upsert into the right table → "1 nieuwe rij in device_locations".
    fake_client.table.assert_called_once_with("device_locations")
    table = fake_client.table.return_value
    table.upsert.assert_called_once()
    table.upsert.return_value.execute.assert_called_once()

    row = table.upsert.call_args.args[0]
    assert row["device_name"] == "TRK-007"
    assert row["lat"] == 51.2194
    assert row["lon"] == 4.4025
    assert row["time"] == "2025-05-28T10:00:00Z"


# ---------------------------------------------------------------------------
# TC-B — Zelfde bericht opnieuw → geen duplicaat (upsert)
# ---------------------------------------------------------------------------
def test_tc_b_repeat_message_dedup_contract(subscriber_with_fake_db):
    subscriber, fake_client = subscriber_with_fake_db

    # Deliver the identical message twice.
    subscriber.on_message(None, None, _FakeMsg(VALID_PAYLOAD))
    subscriber.on_message(None, None, _FakeMsg(VALID_PAYLOAD))

    table = fake_client.table.return_value
    assert table.upsert.call_count == 2

    # De-duplication is delegated to the DB UNIQUE(device_name, time) constraint
    # via on_conflict. The unit-level guarantee is that BOTH writes carry the
    # same on_conflict target and an identical key, so the second is a no-op
    # update rather than an insert → row count stays 1.
    rows = [c.args[0] for c in table.upsert.call_args_list]
    kwargs = [c.kwargs for c in table.upsert.call_args_list]
    assert kwargs[0] == kwargs[1] == {"on_conflict": "device_name,time"}
    assert rows[0]["device_name"] == rows[1]["device_name"]
    assert rows[0]["time"] == rows[1]["time"]


# ---------------------------------------------------------------------------
# TC-C — Ongeldig JSON → fout gelogd, subscriber blijft draaien
# ---------------------------------------------------------------------------
def test_tc_c_invalid_json_logged_survives(subscriber_with_fake_db, capsys):
    subscriber, fake_client = subscriber_with_fake_db

    # Must NOT raise — on_message swallows the parse error so loop_forever lives on.
    subscriber.on_message(None, None, _FakeMsg('niet_geldig_json%%'))

    out = capsys.readouterr().out
    assert "error processing message" in out.lower()   # fout gelogd
    fake_client.table.assert_not_called()              # geen rij in DB


# ---------------------------------------------------------------------------
# TC-D — Bericht zonder lat-veld → graceful skip, fout gelogd, geen rij
# ---------------------------------------------------------------------------
def test_tc_d_missing_lat_graceful_skip(subscriber_with_fake_db, capsys):
    subscriber, fake_client = subscriber_with_fake_db

    no_lat = (
        '{"device_name":"TRK-007","lon":4.4025,'
        '"altitude":0.0,"accuracy":0.0,"time":"2025-05-28T10:00:00Z"}'
    )
    # _upsert raises KeyError('lat'); on_message catches it → no crash.
    subscriber.on_message(None, None, _FakeMsg(no_lat))

    out = capsys.readouterr().out
    assert "error processing message" in out.lower()   # fout gelogd
    # No completed write: execute() never reached for this message.
    fake_client.table.return_value.upsert.return_value.execute.assert_not_called()
