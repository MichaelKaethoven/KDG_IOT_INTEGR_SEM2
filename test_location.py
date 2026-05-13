import sys
sys.path.insert(0, '.')

from location_fetcher import fetch_device_list, fetch_locations_for_device

print("Fetching device list...")
devices = fetch_device_list()

if not devices:
    print("[FAIL] No devices found. Run test_list_devices.py first.")
    sys.exit(1)

# Test the first device only
name, canonic_id = devices[0]
print(f"Requesting locations for: {name!r} ({canonic_id})")
print("(Waiting for FCM push — up to 30 s...)")

locations = fetch_locations_for_device(canonic_id, name, timeout=30)

print()
if not locations:
    print(f"[FAIL] No locations returned for {name!r}.")
    print("       Possible causes: device offline, E2EE keys not initialized,")
    print("       or Find My Device network coverage is low.")
    sys.exit(1)

passed = False
for loc in locations:
    lat, lon = loc['lat'], loc['lon']
    if lat is None:
        print(f"  [semantic] {loc['semantic_location']}  time={loc['time']}")
        continue
    in_range = -90 <= lat <= 90 and -180 <= lon <= 180
    tag = "[OK]  " if in_range else "[WARN]"
    print(f"  {tag} {name!r}: lat={lat:.6f} lon={lon:.6f} "
          f"alt={loc['altitude']}  acc={loc['accuracy']}m  time={loc['time']}  own={loc['is_own_report']}")
    if in_range:
        passed = True

print()
if passed:
    print("[PASS] At least one valid coordinate pair returned.")
else:
    print("[FAIL] No in-range coordinates found.")
    sys.exit(1)
