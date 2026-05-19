import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'libs'))

import hashlib
import time
import datetime
from typing import List, Dict

from Auth.fcm_receiver import FcmReceiver
from FMDNCrypto.foreign_tracker_cryptor import decrypt
from KeyBackup.cloud_key_decryptor import decrypt_aes_gcm
from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import retrieve_identity_key, is_mcu_tracker
from NovaApi.ExecuteAction.LocateTracker.location_request import create_location_request
from NovaApi.ListDevices.nbe_list_devices import request_device_list
from NovaApi.nova_request import nova_request
from NovaApi.scopes import NOVA_ACTION_API_SCOPE
from NovaApi.util import generate_random_uuid
from ProtoDecoders import DeviceUpdate_pb2, Common_pb2
from ProtoDecoders.decoder import parse_device_list_protobuf, get_canonic_ids, parse_device_update_protobuf


def fetch_device_list() -> List[tuple]:
    """Returns list of (device_name, canonic_id) tuples."""
    result_hex = request_device_list()
    device_list = parse_device_list_protobuf(result_hex)
    return get_canonic_ids(device_list)


def fetch_locations_for_device(canonic_id: str, name: str, timeout: int = 30) -> List[Dict]:
    """Fetches and decrypts locations for a single device. Returns list of location dicts."""
    result = None
    request_uuid = generate_random_uuid()

    def handle_response(response):
        nonlocal result
        device_update = parse_device_update_protobuf(response)
        if device_update.fcmMetadata.requestUuid == request_uuid:
            result = device_update

    fcm_token = FcmReceiver().register_for_location_updates(handle_response)
    hex_payload = create_location_request(canonic_id, fcm_token, request_uuid)
    nova_request(NOVA_ACTION_API_SCOPE, hex_payload)

    deadline = time.time() + timeout
    while result is None and time.time() < deadline:
        time.sleep(0.1)

    if result is None:
        print(f"[fetch] timeout waiting for location response for {name}")
        return []

    return _decrypt_to_dicts(result, name)


def _decrypt_to_dicts(device_update_protobuf, name: str) -> List[Dict]:
    device_registration = device_update_protobuf.deviceMetadata.information.deviceRegistration
    identity_key = retrieve_identity_key(device_registration)
    locations_proto = (
        device_update_protobuf.deviceMetadata.information
        .locationInformation.reports.recentLocationAndNetworkLocations
    )
    is_mcu = is_mcu_tracker(device_registration)

    network_locations = list(locations_proto.networkLocations)
    network_times = list(locations_proto.networkLocationTimestamps)

    if locations_proto.HasField("recentLocation"):
        network_locations.append(locations_proto.recentLocation)
        network_times.append(locations_proto.recentLocationTimestamp)

    results = []
    for loc, ts in zip(network_locations, network_times):

        if loc.status == Common_pb2.Status.SEMANTIC:
            results.append({
                'device_name': name,
                'lat': None,
                'lon': None,
                'altitude': None,
                'accuracy': None,
                'time': datetime.datetime.utcfromtimestamp(ts.seconds).isoformat() + 'Z',
                'is_own_report': True,
                'semantic_location': loc.semanticLocation.locationName,
            })
            continue

        encrypted_location = loc.geoLocation.encryptedReport.encryptedLocation
        public_key_random = loc.geoLocation.encryptedReport.publicKeyRandom

        try:
            if public_key_random == b"":
                key_hash = hashlib.sha256(identity_key).digest()
                decrypted_bytes = decrypt_aes_gcm(key_hash, encrypted_location)
            else:
                time_offset = 0 if is_mcu else loc.geoLocation.deviceTimeOffset
                decrypted_bytes = decrypt(identity_key, encrypted_location, public_key_random, time_offset)
        except Exception as e:
            print(f"[decrypt] failed for {name}: {e}")
            continue

        proto_loc = DeviceUpdate_pb2.Location()
        proto_loc.ParseFromString(decrypted_bytes)

        results.append({
            'device_name': name,
            'lat': proto_loc.latitude / 1e7,
            'lon': proto_loc.longitude / 1e7,
            'altitude': proto_loc.altitude,
            'accuracy': loc.geoLocation.accuracy,
            'time': datetime.datetime.utcfromtimestamp(ts.seconds).isoformat() + 'Z',
            'is_own_report': loc.geoLocation.encryptedReport.isOwnReport,
            'semantic_location': None,
        })

    return results


def fetch_all_locations(timeout_per_device: int = 30) -> List[Dict]:
    """Fetches the latest location for every device on the account."""
    devices = fetch_device_list()
    all_locations = []
    for name, canonic_id in devices:
        locs = fetch_locations_for_device(canonic_id, name, timeout=timeout_per_device)
        all_locations.extend(locs)
    return all_locations
