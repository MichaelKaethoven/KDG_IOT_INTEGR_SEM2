"""Reads runtime tuning knobs from the Supabase ``app_settings`` table so the
middleware can pick up changes made in the portal Settings page without a
restart. Falls back to env/hardcoded defaults when a key is absent or Supabase
is unconfigured/unreachable, so the middleware keeps running either way.

The key names, casts and defaults mirror ``webapp/settings_store.py`` — the two
services don't share code, so keep them in sync by hand.
"""

import os

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# (key, cast, env var for default, hardcoded default)
_SPEC = [
    ("poll_interval", int, "POLL_INTERVAL", 300),
    ("location_batch_size", int, "LOCATION_BATCH_SIZE", 8),
    ("location_batch_delay", float, "LOCATION_BATCH_DELAY", 2.0),
    ("location_timeout", int, "LOCATION_TIMEOUT", 30),
]
_CASTS = {key: cast for key, cast, _, _ in _SPEC}

_supabase = None
_warned = False


def _get_supabase():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return None
        from supabase import create_client
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def _env_defaults() -> dict:
    out = {}
    for key, cast, env, default in _SPEC:
        raw = os.environ.get(env)
        if raw:
            try:
                out[key] = cast(raw)
                continue
            except (TypeError, ValueError):
                pass
        out[key] = default
    return out


def load_runtime_settings() -> dict:
    """Effective middleware settings: the stored value from ``app_settings`` when
    present and castable, otherwise the env/hardcoded default."""
    global _warned
    values = _env_defaults()
    client = _get_supabase()
    if client is None:
        return values
    try:
        rows = client.table("app_settings").select("key, value").execute().data
    except Exception as e:
        if not _warned:
            print(f"[settings] could not read app_settings, using defaults: {e}")
            _warned = True
        return values
    for row in rows or []:
        key = row.get("key")
        if key not in _CASTS:
            continue
        try:
            values[key] = _CASTS[key](row["value"])
        except (TypeError, ValueError):
            pass
    return values
