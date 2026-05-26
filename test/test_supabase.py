"""Integration test: hits Google Find Hub + Supabase. Requires Auth/secrets.json + SUPABASE_URL/KEY."""
import pytest

from location_fetcher import fetch_device_list, fetch_locations_for_device
from subscriber import _upsert


@pytest.mark.integration
def test_upsert_one_device_to_supabase():
    print("Fetching device list...")
    devices = fetch_device_list()
    print(f"Found {len(devices)} device(s)")
    if not devices:
        pytest.fail("No devices found.")

    name, canonic_id = devices[0]
    print(f"Fetching location for: {name!r} ...")
    locs = fetch_locations_for_device(canonic_id, name, timeout=30)
    print(f"Got {len(locs)} location(s)")
    if not locs:
        pytest.fail("No locations returned.")

    for loc in locs:
        if loc["lat"] is not None:
            print(f"  lat={loc['lat']:.6f} lon={loc['lon']:.6f} time={loc['time']}")
        else:
            print(f"  [semantic] {loc['semantic_location']} time={loc['time']}")

    print("Pushing to Supabase...")
    for loc in locs:
        _upsert(loc)
    print("Done.")
