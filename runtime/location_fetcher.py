import hashlib
import os
import threading
import time
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    done = threading.Event()
    request_uuid = generate_random_uuid()

    def handle_response(response):
        nonlocal result
        device_update = parse_device_update_protobuf(response)
        if device_update.fcmMetadata.requestUuid == request_uuid:
            result = device_update
            done.set()

    receiver = FcmReceiver()
    fcm_token = receiver.register_for_location_updates(handle_response)
    try:
        hex_payload = create_location_request(canonic_id, fcm_token, request_uuid)
        nova_request(NOVA_ACTION_API_SCOPE, hex_payload)

        done.wait(timeout=timeout)
    finally:
        receiver.unregister_for_location_updates(handle_response)

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
                'time': datetime.datetime.fromtimestamp(ts.seconds, tz=datetime.timezone.utc).isoformat(),
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
            'time': datetime.datetime.fromtimestamp(ts.seconds, tz=datetime.timezone.utc).isoformat(),
            'is_own_report': loc.geoLocation.encryptedReport.isOwnReport,
            'semantic_location': None,
        })

    return results


# How many devices to request locations for at once, and how long to pause
# between batches. Google rate-limits bursts of location requests, so we cap
# concurrency and space batches out instead of firing every device at once.
LOCATION_BATCH_SIZE = int(os.environ.get("LOCATION_BATCH_SIZE", 8))
LOCATION_BATCH_DELAY = float(os.environ.get("LOCATION_BATCH_DELAY", 2.0))


def fetch_all_locations(timeout_per_device: int = 30,
                        batch_size: int = LOCATION_BATCH_SIZE,
                        batch_delay: float = LOCATION_BATCH_DELAY) -> List[Dict]:
    """Fetches the latest location for every device on the account.

    Devices are processed in batches of ``batch_size`` (each batch fetched in
    parallel, batches run sequentially) with a ``batch_delay``-second pause
    between batches to avoid tripping Google's rate limits.
    """
    devices = fetch_device_list()
    if not devices:
        return []

    all_locations = []
    for start in range(0, len(devices), batch_size):
        batch = devices[start:start + batch_size]
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {
                pool.submit(fetch_locations_for_device, canonic_id, name, timeout_per_device): name
                for name, canonic_id in batch
            }
            for fut in as_completed(futures):
                try:
                    all_locations.extend(fut.result())
                except Exception as e:
                    print(f"[fetch] error for {futures[fut]}: {e}")
        if batch_delay and start + batch_size < len(devices):
            time.sleep(batch_delay)
    return all_locations
