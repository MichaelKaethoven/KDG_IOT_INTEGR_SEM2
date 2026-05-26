"""Integration test: hits Google Find Hub. Requires Auth/secrets.json."""
import pytest

from location_fetcher import fetch_device_list, fetch_locations_for_device


@pytest.mark.integration
def test_fetch_one_device_location():
    print("Fetching device list...")
    devices = fetch_device_list()
    if not devices:
        pytest.fail("No devices found. Run test_list_devices first.")

    name, canonic_id = devices[0]
    print(f"Requesting locations for: {name!r} ({canonic_id})")
    print("(Waiting for FCM push — up to 30 s...)")

    locations = fetch_locations_for_device(canonic_id, name, timeout=30)
    if not locations:
        pytest.fail(
            f"No locations returned for {name!r}. "
            "Device may be offline, E2EE keys not initialized, or low FMD coverage."
        )

    passed = False
    for loc in locations:
        lat, lon = loc["lat"], loc["lon"]
        if lat is None:
            print(f"  [semantic] {loc['semantic_location']}  time={loc['time']}")
            continue
        in_range = -90 <= lat <= 90 and -180 <= lon <= 180
        tag = "[OK]  " if in_range else "[WARN]"
        print(
            f"  {tag} {name!r}: lat={lat:.6f} lon={lon:.6f} "
            f"alt={loc['altitude']}  acc={loc['accuracy']}m  time={loc['time']}  own={loc['is_own_report']}"
        )
        if in_range:
            passed = True

    assert passed, "No in-range coordinates found."
