import sys
import os

_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(_root, 'libs'))
sys.path.insert(0, os.path.join(_root, 'runtime'))

from location_fetcher import fetch_device_list, fetch_locations_for_device
from middleware import _push_to_supabase

print("Fetching device list...")
devices = fetch_device_list()
print(f"Found {len(devices)} device(s)")

if not devices:
    print("[FAIL] No devices found.")
    sys.exit(1)

name, canonic_id = devices[0]
print(f"Fetching location for: {name!r} ...")
locs = fetch_locations_for_device(canonic_id, name, timeout=30)
print(f"Got {len(locs)} location(s)")

if not locs:
    print("[FAIL] No locations returned.")
    sys.exit(1)

for loc in locs:
    if loc["lat"] is not None:
        print(f"  lat={loc['lat']:.6f} lon={loc['lon']:.6f} time={loc['time']}")
    else:
        print(f"  [semantic] {loc['semantic_location']} time={loc['time']}")

print()
print("Pushing to Supabase...")
_push_to_supabase(locs)
print("Done.")
