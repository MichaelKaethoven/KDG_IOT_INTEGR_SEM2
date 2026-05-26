"""Unit tests for location_fetcher._decrypt_to_dicts.

We mock the crypto and protobuf parse functions so the test runs offline.
Inputs are simple object stand-ins (SimpleNamespace) that match the attribute
shape the function reads.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_geo_loc(status, *, public_key_random=b"\x01", encrypted_location=b"ciphertext",
                  device_time_offset=0, accuracy=12.0, is_own=False, semantic_name=""):
    return SimpleNamespace(
        status=status,
        semanticLocation=SimpleNamespace(locationName=semantic_name),
        geoLocation=SimpleNamespace(
            encryptedReport=SimpleNamespace(
                publicKeyRandom=public_key_random,
                encryptedLocation=encrypted_location,
                isOwnReport=is_own,
            ),
            deviceTimeOffset=device_time_offset,
            accuracy=accuracy,
        ),
    )


def _make_locations_proto(network_locations, network_times, recent=None, recent_ts=None):
    has_recent = recent is not None
    proto = MagicMock()
    proto.networkLocations = network_locations
    proto.networkLocationTimestamps = network_times
    proto.HasField = lambda name: name == "recentLocation" and has_recent
    proto.recentLocation = recent
    proto.recentLocationTimestamp = recent_ts
    return proto


def _make_device_update(locations_proto):
    return SimpleNamespace(
        deviceMetadata=SimpleNamespace(
            information=SimpleNamespace(
                deviceRegistration=SimpleNamespace(),
                locationInformation=SimpleNamespace(
                    reports=SimpleNamespace(recentLocationAndNetworkLocations=locations_proto)
                ),
            )
        )
    )


def test_semantic_location_returns_named_location_without_coords(monkeypatch):
    import location_fetcher
    from ProtoDecoders import Common_pb2

    monkeypatch.setattr(location_fetcher, "retrieve_identity_key", lambda r: b"identity-key")
    monkeypatch.setattr(location_fetcher, "is_mcu_tracker", lambda r: False)

    sem = _make_geo_loc(Common_pb2.Status.SEMANTIC, semantic_name="Home")
    ts = SimpleNamespace(seconds=1700000000)
    locations_proto = _make_locations_proto([sem], [ts])
    dev_update = _make_device_update(locations_proto)

    out = location_fetcher._decrypt_to_dicts(dev_update, "Tracker-A")

    assert len(out) == 1
    assert out[0]["device_name"] == "Tracker-A"
    assert out[0]["lat"] is None
    assert out[0]["lon"] is None
    assert out[0]["semantic_location"] == "Home"
    assert out[0]["time"].endswith("+00:00")


def test_aes_gcm_path_taken_when_public_key_random_empty(monkeypatch):
    import location_fetcher
    from ProtoDecoders import Common_pb2

    monkeypatch.setattr(location_fetcher, "retrieve_identity_key", lambda r: b"identity-key")
    monkeypatch.setattr(location_fetcher, "is_mcu_tracker", lambda r: False)

    aes_mock = MagicMock(return_value=b"\x00" * 64)
    decrypt_mock = MagicMock()
    monkeypatch.setattr(location_fetcher, "decrypt_aes_gcm", aes_mock)
    monkeypatch.setattr(location_fetcher, "decrypt", decrypt_mock)

    fake_loc = MagicMock()
    fake_loc.latitude = 510543000   # 51.0543° * 1e7
    fake_loc.longitude = 37174000   # 3.7174° * 1e7
    fake_loc.altitude = 15
    fake_location_cls = MagicMock(return_value=fake_loc)
    monkeypatch.setattr(location_fetcher.DeviceUpdate_pb2, "Location", fake_location_cls)

    geo = _make_geo_loc(Common_pb2.Status.LAST_KNOWN, public_key_random=b"", accuracy=8.0)
    ts = SimpleNamespace(seconds=1700000000)
    dev_update = _make_device_update(_make_locations_proto([geo], [ts]))

    out = location_fetcher._decrypt_to_dicts(dev_update, "Tracker-B")

    aes_mock.assert_called_once()
    decrypt_mock.assert_not_called()
    assert len(out) == 1
    assert out[0]["lat"] == 51.0543
    assert out[0]["lon"] == 3.7174
    assert out[0]["accuracy"] == 8.0


def test_foreign_decrypt_path_taken_when_public_key_random_set(monkeypatch):
    import location_fetcher
    from ProtoDecoders import Common_pb2

    monkeypatch.setattr(location_fetcher, "retrieve_identity_key", lambda r: b"identity-key")
    monkeypatch.setattr(location_fetcher, "is_mcu_tracker", lambda r: False)

    aes_mock = MagicMock()
    decrypt_mock = MagicMock(return_value=b"\x00" * 64)
    monkeypatch.setattr(location_fetcher, "decrypt_aes_gcm", aes_mock)
    monkeypatch.setattr(location_fetcher, "decrypt", decrypt_mock)

    fake_loc = MagicMock(latitude=0, longitude=0, altitude=0)
    monkeypatch.setattr(location_fetcher.DeviceUpdate_pb2, "Location",
                        MagicMock(return_value=fake_loc))

    geo = _make_geo_loc(Common_pb2.Status.LAST_KNOWN,
                        public_key_random=b"\xaa\xbb", device_time_offset=42)
    ts = SimpleNamespace(seconds=1700000000)
    dev_update = _make_device_update(_make_locations_proto([geo], [ts]))

    location_fetcher._decrypt_to_dicts(dev_update, "Tracker-C")

    aes_mock.assert_not_called()
    decrypt_mock.assert_called_once_with(b"identity-key", b"ciphertext", b"\xaa\xbb", 42)


def test_decrypt_failure_is_swallowed_and_skips_location(monkeypatch):
    import location_fetcher
    from ProtoDecoders import Common_pb2

    monkeypatch.setattr(location_fetcher, "retrieve_identity_key", lambda r: b"k")
    monkeypatch.setattr(location_fetcher, "is_mcu_tracker", lambda r: False)
    monkeypatch.setattr(location_fetcher, "decrypt_aes_gcm",
                        MagicMock(side_effect=RuntimeError("bad tag")))

    geo = _make_geo_loc(Common_pb2.Status.LAST_KNOWN, public_key_random=b"")
    ts = SimpleNamespace(seconds=1700000000)
    dev_update = _make_device_update(_make_locations_proto([geo], [ts]))

    out = location_fetcher._decrypt_to_dicts(dev_update, "Tracker-D")
    assert out == []
