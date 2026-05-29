import os
from datetime import datetime, timezone

from db import get_db

# Ordered spec for the Settings page. Each entry's effective default is read
# from its env var (matching the value the services already start with), falling
# back to the hardcoded default — so the page shows correct values even before
# any setting has ever been saved.
SETTINGS_SPEC = [
    {"key": "poll_interval", "label": "Poll interval (seconds)",
     "help": "Seconds between Google polls. Google's practical floor is 300; lower risks rate-limiting.",
     "kind": int, "env": "POLL_INTERVAL", "default": 300, "min": 300, "max": 86400, "step": 1},
    {"key": "location_batch_size", "label": "Location batch size",
     "help": "Devices whose locations are requested in parallel per batch. 5–10 is safe.",
     "kind": int, "env": "LOCATION_BATCH_SIZE", "default": 8, "min": 1, "max": 50, "step": 1},
    {"key": "location_batch_delay", "label": "Location batch delay (seconds)",
     "help": "Pause between batches to avoid bursting Google's rate limits.",
     "kind": float, "env": "LOCATION_BATCH_DELAY", "default": 2.0, "min": 0.0, "max": 60.0, "step": 0.5},
    {"key": "location_timeout", "label": "Location timeout (seconds)",
     "help": "How long to wait for each device's location response before giving up.",
     "kind": int, "env": "LOCATION_TIMEOUT", "default": 30, "min": 5, "max": 120, "step": 1},
    {"key": "tracker_stale_hours", "label": "Tracker stale hours",
     "help": "Hours without a ping before a tracker is flagged stale (red) in the Trackers list.",
     "kind": int, "env": "TRACKER_STALE_HOURS", "default": 24, "min": 1, "max": 8760, "step": 1},
]

_SPEC_BY_KEY = {s["key"]: s for s in SETTINGS_SPEC}


def _default(spec):
    raw = os.environ.get(spec["env"]) if spec["env"] else None
    if not raw:
        return spec["default"]
    try:
        return spec["kind"](raw)
    except (TypeError, ValueError):
        return spec["default"]


def _cast(spec, raw):
    """Cast a stored/submitted string to the spec's type, returning None if it
    is not a number or falls outside the allowed range."""
    try:
        value = spec["kind"](raw)
    except (TypeError, ValueError):
        return None
    if value < spec["min"] or value > spec["max"]:
        return None
    return value


def get_settings() -> dict:
    """Effective value for every setting: the stored value when present and
    valid, otherwise the env/hardcoded default. Never raises — on a DB error it
    returns defaults so a page render can't be taken down by Supabase."""
    values = {s["key"]: _default(s) for s in SETTINGS_SPEC}
    try:
        rows = get_db().table("app_settings").select("key, value").execute().data
    except Exception:
        return values
    for row in rows or []:
        spec = _SPEC_BY_KEY.get(row["key"])
        if spec is None:
            continue
        cast = _cast(spec, row["value"])
        if cast is not None:
            values[row["key"]] = cast
    return values


def get_setting(key):
    """Effective value for a single setting key."""
    return get_settings()[key]


def save_settings(form) -> dict:
    """Validate and persist submitted form values. Returns {key: error message}
    for any invalid field; an empty dict means everything validated and saved."""
    errors = {}
    to_write = []
    now = datetime.now(timezone.utc).isoformat()
    for spec in SETTINGS_SPEC:
        value = _cast(spec, (form.get(spec["key"]) or "").strip())
        if value is None:
            errors[spec["key"]] = f"Must be a number between {spec['min']} and {spec['max']}."
            continue
        to_write.append({"key": spec["key"], "value": str(value), "updated_at": now})
    if errors:
        return errors
    get_db().table("app_settings").upsert(to_write).execute()
    return {}
