#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import binascii
from NovaApi.nova_request import nova_request
from NovaApi.scopes import NOVA_LIST_DEVICS_API_SCOPE
from NovaApi.util import generate_random_uuid
from ProtoDecoders import DeviceUpdate_pb2
from ProtoDecoders.decoder import parse_device_list_protobuf, get_canonic_ids


def request_device_list():
    hex_payload = create_device_list_request()
    return nova_request(NOVA_LIST_DEVICS_API_SCOPE, hex_payload)


def create_device_list_request():
    wrapper = DeviceUpdate_pb2.DevicesListRequest()
    wrapper.deviceListRequestPayload.type = DeviceUpdate_pb2.DeviceType.SPOT_DEVICE
    wrapper.deviceListRequestPayload.id = generate_random_uuid()
    binary_payload = wrapper.SerializeToString()
    return binascii.hexlify(binary_payload).decode('utf-8')


def list_devices():
    result_hex = request_device_list()
    device_list = parse_device_list_protobuf(result_hex)
    for name, canonic_id in get_canonic_ids(device_list):
        print(f"{name}: {canonic_id}")


if __name__ == '__main__':
    list_devices()
