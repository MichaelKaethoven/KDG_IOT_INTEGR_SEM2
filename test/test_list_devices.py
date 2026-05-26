"""Integration test: hits Google Find Hub. Requires Auth/secrets.json."""
import pytest

from NovaApi.ListDevices.nbe_list_devices import request_device_list
from ProtoDecoders.decoder import parse_device_list_protobuf, get_canonic_ids


@pytest.mark.integration
def test_list_devices():
    print("Requesting device list from Google Find Hub...")
    result_hex = request_device_list()
    device_list = parse_device_list_protobuf(result_hex)
    canonic_ids = get_canonic_ids(device_list)

    if not canonic_ids:
        pytest.fail("No devices returned. Check that Find My Device is enabled.")

    for i, (name, canonic_id) in enumerate(canonic_ids, 1):
        print(f"  {i}. {name!r}  id={canonic_id}")

    assert len(canonic_ids) > 0
