import sys
import os

_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(_root, 'libs'))

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import parse_device_list_protobuf, get_canonic_ids

print("Requesting device list from Google Find Hub...")
result_hex = request_device_list()
device_list = parse_device_list_protobuf(result_hex)
canonic_ids = get_canonic_ids(device_list)

print()
if not canonic_ids:
    print("[FAIL] No devices returned. Check that Find My Device is enabled.")
    sys.exit(1)

for i, (name, canonic_id) in enumerate(canonic_ids, 1):
    print(f"  {i}. {name!r}  id={canonic_id}")

print()
print(f"[PASS] {len(canonic_ids)} device(s) found.")
