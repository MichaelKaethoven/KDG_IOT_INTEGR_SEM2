"""Unit tests for subscriber._upsert — verify the row dict shape sent to Supabase."""
from unittest.mock import MagicMock


def test_upsert_passes_expected_row_shape(monkeypatch):
    import subscriber

    fake_client = MagicMock()
    monkeypatch.setattr(subscriber, "_get_supabase", lambda: fake_client)

    payload = {
        "device_name": "Tracker-A",
        "lat": 51.0543,
        "lon": 3.7174,
        "altitude": 12.5,
        "accuracy": 8.0,
        "time": "2026-05-21T10:00:00+00:00",
    }
    subscriber._upsert(payload)

    fake_client.table.assert_called_once_with("device_locations")
    table = fake_client.table.return_value
    table.upsert.assert_called_once()
    row, kwargs = table.upsert.call_args.args, table.upsert.call_args.kwargs
    assert row[0] == {
        "device_name": "Tracker-A",
        "lat": 51.0543,
        "lon": 3.7174,
        "altitude": 12.5,
        "accuracy": 8.0,
        "time": "2026-05-21T10:00:00+00:00",
    }
    assert kwargs == {"on_conflict": "device_name,time"}
    table.upsert.return_value.execute.assert_called_once()


def test_upsert_defaults_missing_altitude_and_accuracy_to_zero(monkeypatch):
    import subscriber

    fake_client = MagicMock()
    monkeypatch.setattr(subscriber, "_get_supabase", lambda: fake_client)

    payload = {
        "device_name": "Tracker-B",
        "lat": 0.0,
        "lon": 0.0,
        "time": "2026-05-21T10:00:00+00:00",
    }
    subscriber._upsert(payload)

    row = fake_client.table.return_value.upsert.call_args.args[0]
    assert row["altitude"] == 0.0
    assert row["accuracy"] == 0.0


def test_upsert_skips_when_client_not_configured(monkeypatch, capsys):
    import subscriber

    monkeypatch.setattr(subscriber, "_get_supabase", lambda: None)

    subscriber._upsert({"device_name": "X", "lat": 1.0, "lon": 2.0, "time": "t"})

    out = capsys.readouterr().out
    assert "skipping" in out.lower()
