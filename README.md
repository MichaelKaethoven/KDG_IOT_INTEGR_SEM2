# GoogleFindMyTools — Integration Project 2025-2026 Sem 2

> **Setting this up or handing it over?** Read **[`DEPLOYMENT.md`](DEPLOYMENT.md)** —
> a complete, step-by-step guide to configuring, running and deploying the whole
> system from a fresh clone.

**Team**

| GitHub            | Name              |
| ----------------- | ----------------- |
| Michael Kaethoven | Michael Kaethoven |
| kroempoek         | Kevin Wong        |
| Liam77            | Liam Luyten       |
| chahidben         | Chahid Benhaddou  |
| 100dirhams        | Mohamed Bata      |

---

## What this project does

This project integrates **school-provided BLE trackers** with **Google's Find My Device network** and builds a full backend pipeline to poll, decrypt, store, and visualize their locations in real time.

The core Google API interaction layer is based on the reverse-engineering work by [**Leon Böttger (biemster)**](https://github.com/leonbottger/GoogleFindMyTools). On top of that, we built a runtime middleware, MQTT pub/sub pipeline, Supabase persistence layer, and a Grafana dashboard — all described below.

### Hardware choice — why not ESP32?

We researched and partially implemented an ESP32-based custom beacon (see `libs/SpotApi/CreateBleDevice/` and `libs/FMDNCrypto/eid_generator.py`), but decided against using it at scale for three reasons:

- **Dimensional restrictions** — the ESP32 DevKit form factor was too large for the intended enclosures
- **Setup overhead** — provisioning 200+ individual ESP32s with unique advertisement keys is not a realistic one-time operation
- **Re-registration every 4 days** — Google's Find My network only retains a beacon's pre-computed EID schedule for 4 days (`max_truncated_eid_seconds_server`), after which each device must re-advertise itself to Google. At scale this becomes an unmanageable maintenance burden.

The school-provided BLE trackers handle all of the above out of the box, making them the practical choice for a 200+ device deployment.

---

## Repository structure

```
GoogleFindMyTools/
├── libs/                  ← Core library (mostly upstream, see below)
│   ├── Auth/              ← Google OAuth + Firebase/FCM auth
│   ├── FMDNCrypto/        ← FMDN encryption / key derivation
│   ├── KeyBackup/         ← Cloud key backup & decryption chain
│   ├── NovaApi/           ← Google Nova REST API client
│   ├── SpotApi/           ← Google Spot gRPC API client
│   └── ProtoDecoders/     ← Protobuf schemas + decoder helpers
├── runtime/               ← OUR CODE — middleware, subscriber, fetcher
│   ├── middleware.py
│   ├── subscriber.py
│   └── location_fetcher.py
├── setup/
│   └── main.py            ← One-time device registration entry point
├── test/                  ← OUR CODE — integration tests
│   ├── test_list_devices.py
│   ├── test_location.py
│   └── test_supabase.py
├── findhub.service        ← systemd unit for deploying middleware
├── fly.grafana.toml       ← Grafana deployment config (Fly.io)
└── requirements.txt
```

---

## Upstream library layer — Leon Böttger's GoogleFindMyTools

> Original repo: [https://github.com/leonbottger/GoogleFindMyTools](https://github.com/leonbottger/GoogleFindMyTools)
> All code in `libs/` is © 2024 Leon Böttger unless noted otherwise.

The upstream library handles the complete interaction with Google's private APIs. A brief summary of each module:

### Auth (`libs/Auth/`)

Handles all Google account authentication. Authenticates via `accounts.google.com/EmbeddedSetup` using Selenium to extract an OAuth token, which is exchanged for a long-lived **AAS token** (Account Authentication Service). From the AAS token it derives two scoped OAuth tokens:

- **ADM token** — `android_device_manager` scope, used for Nova API calls
- **Spot token** — `spot` scope via Google Play Services, used for Spot API calls

Additionally it registers a virtual Android device with **Google's Firebase Cloud Messaging (FCM)** infrastructure, impersonating the `com.google.android.apps.adm` app. This gives the system a push-capable endpoint (`mtalk.google.com:5228`) where Google delivers location update responses in real time.

All credentials are cached in `secrets.json`.

### FMDNCrypto (`libs/FMDNCrypto/`)

Implements Google's **Find My Device Network (FMDN)** encryption spec:

- `key_derivation.py` — derives recovery, ringing, and tracking sub-keys from an identity key using truncated SHA-256
- `eid_generator.py` — generates rotating **Ephemeral Identifiers** (EIDs) from the identity key + timestamp; rotation period is 1024 seconds
- `foreign_tracker_cryptor.py` — full ECDH decryption on **SECP160r1** with AES-EAX-256 for crowdsourced ("network") location reports

### KeyBackup (`libs/KeyBackup/`)

Retrieves and decrypts the account's master **owner key** from Google's cloud backup. The decryption chain is:

```
Phone PIN → Scrypt → LSKF Hash
  → Recovery Key → Application Key → Security Domain Key
    → Shared Key (ECDH) → Owner Key → Identity Key (EIK)
```

The shared key itself is extracted via a browser-based OAuth session using JavaScript injection to intercept Google's internal `setVaultSharedKeys()` vault callback.

### NovaApi (`libs/NovaApi/`)

REST/protobuf client for `https://android.googleapis.com/nova/`. Two operations:

- `nbe_list_devices` — retrieves all paired Find My devices on the account
- `nbe_execute_action` — sends a locate request for a specific device; Google pings the crowdsourced network and delivers the encrypted result back via FCM push

### SpotApi (`libs/SpotApi/`)

gRPC client for `https://spot-pa.googleapis.com/google.internal.spot.v1.SpotService/`. Handles:

- `CreateBleDevice` — registers an ESP32 as a legitimate Google Find My beacon, uploading its EID rotation schedule and encrypted identity key
- `GetEidInfoForE2eeDevices` — fetches the encrypted owner key from Google's servers

`grpc_parser.py` handles the gRPC wire framing (`[compression byte][4-byte length][protobuf]`).

---

## Our code

### `libs/ProtoDecoders/decoder.py`

A custom protobuf parsing and pretty-printing utility we wrote on top of the upstream protobuf schemas. Provides:

- `parse_device_list_protobuf(hex)` — deserializes a `DevicesList` response
- `parse_device_update_protobuf(hex)` — deserializes a `DeviceUpdate` location response
- `get_canonic_ids(device_list)` — walks the device list protobuf and extracts `(device_name, canonic_id)` tuples for both Android and SPOT device types
- `custom_message_formatter` — a recursive protobuf formatter that renders byte fields as hex and Unix timestamps as human-readable Berlin-timezone datetimes
- A `__main__` block that re-compiles all `.proto` files via `protoc`

### `libs/NovaApi/ExecuteAction/LocateTracker/location_request.py`

Builds and serializes the `ExecuteActionRequest` protobuf for a locate operation. Sets `contributorType = FMDN_ALL_LOCATIONS` so the request collects both own-device and crowdsourced network reports. Also contains `get_location_data_for_device()`, an earlier synchronous helper that waits on the FCM callback and then immediately calls the upstream decryption flow.

### `libs/SpotApi/CreateBleDevice/create_ble_device.py`

Researched and implemented as part of the ESP32 feasibility study; **not used in the final deployment** (see hardware choice above).

Implements the full ESP32 beacon registration flow:

1. Fetches the account owner key via `GetEidInfoForE2eeDevices`
2. Generates a fresh 32-byte identity key (EIK) and derives an initial EID
3. Builds a `RegisterBleDeviceRequest` protobuf — device name, type, image URL, capabilities, rotation exponent (10 = ~17 min), and a pre-computed list of 336 truncated EIDs covering 4 days of rotations
4. Encrypts the EIK with the owner key (AES-GCM) and flips its bits so Android devices cannot decrypt it
5. Derives ring, recovery, and tracking sub-keys from the EIK
6. Sends the request to `CreateBleDevice` via the Spot gRPC API
7. Prints the raw advertisement key to be flashed onto the ESP32 firmware

The 4-day EID schedule limit (step 3) was one of the key factors that made ESP32 impractical at the 200+ device scale we needed.

### `runtime/location_fetcher.py`

The main location-fetching engine used by the middleware. Three public functions:

- **`fetch_device_list()`** — lists all paired devices by calling Nova `nbe_list_devices` and parsing canonic IDs from the protobuf response
- **`fetch_locations_for_device(canonic_id, name, timeout=30)`** — registers an FCM callback, fires a Nova `nbe_execute_action` locate request, waits up to `timeout` seconds for the FCM push response, then decrypts all returned location reports and returns them as plain dicts
- **`fetch_all_locations()`** — iterates every device on the account and aggregates all results

Decryption handles both report types:

- **Own reports** (`publicKeyRandom == b""`) — AES-GCM with `SHA256(identity_key)` as key
- **Network/crowdsourced reports** — delegated to `foreign_tracker_cryptor.decrypt()` (SECP160r1 ECDH + AES-EAX)

Semantic (non-GPS) locations are returned with `lat=None` and a `semantic_location` name string.

### `runtime/middleware.py`

A **Flask + MQTT polling service** — the main runtime process, managed by `findhub.service`.

- Spawns a background thread that calls `fetch_all_locations()` every `POLL_INTERVAL` seconds (default: 300 s, overridable via env var or `--interval`)
- Caches the last result in memory under a thread lock
- Publishes each device's location to the MQTT broker on topic `findmy/devices/<device_name>/location` (QoS 1, retained)
- Exposes two HTTP endpoints:
  - `GET /devices` — returns the cached location list as JSON, with a `last_poll` timestamp
  - `GET /healthz` — liveness probe for deployment health checks
- MQTT connection uses TLS (`client.tls_set()`) and username/password auth; all configured via environment variables (`MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD`, `MQTT_TOPIC`)

### `runtime/subscriber.py`

An **MQTT subscriber** that persists incoming location messages to Supabase.

- Subscribes to `findmy/devices/+/location` (wildcard for all devices)
- On each message, upserts a row into the `device_locations` Supabase table with `ON CONFLICT (device_name, time)` to avoid duplicates
- Runs indefinitely via `client.loop_forever()`
- Entirely driven by environment variables: `MQTT_HOST/PORT/USER/PASSWORD`, `SUPABASE_URL`, `SUPABASE_KEY`

### `test/`

Three standalone integration test scripts:

| File                   | What it tests                                                                                                 |
| ---------------------- | ------------------------------------------------------------------------------------------------------------- |
| `test_list_devices.py` | Calls Nova API and prints all devices found on the account                                                    |
| `test_location.py`     | Fetches and decrypts locations for the first device; passes if at least one valid coordinate pair is returned |
| `test_supabase.py`     | Full end-to-end: fetch location → push to Supabase → verify no exception                                      |

### Deployment

**`findhub.service`** — systemd unit that runs `middleware.py` as the `findhub` user from `/opt/findhub`, reads environment from `/opt/findhub/.env`, and restarts on failure with a 10-second cooldown.

**`fly.grafana.toml`** — deploys Grafana 11.0.0 to Fly.io (Amsterdam) with:

- Anonymous viewer access (no login required for dashboards)
- Supabase PostgreSQL as the datasource
- Persistent volume for dashboard state
- iframe embedding enabled

---

## Data flow

```
ESP32  (BLE advertising rotating EIDs) or any Find Hub compatible tracker
        ↓  crowdsourced via nearby Android devices
Google Find My Device network
        ↓  Nova API (nbe_execute_action)
location_fetcher.py  ←  FCM push callback
        ↓
middleware.py  (in-memory cache + /devices HTTP endpoint)
        ↓  MQTT (TLS, QoS 1, retained)
MQTT broker
        ↓
subscriber.py
        ↓
Supabase PostgreSQL  (device_locations table)
        ↓
Grafana dashboard  (Fly.io, anonymous viewer)
```

---

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Run `setup/main.py` once — this authenticates with Google, registers the FCM device identity, and registers the ESP32 beacon. Note down the printed **Advertisement Key** and flash it to the ESP32 firmware.
3. Configure environment variables (see `middleware.py` and `subscriber.py` for the full list).
4. Start the middleware: `python runtime/middleware.py`
5. Start the subscriber: `python runtime/subscriber.py`
6. Deploy Grafana: `fly deploy --config fly.grafana.toml`

For production, install `findhub.service` as a systemd unit on the host running the middleware.

---

## Safety concerns & risks

### Google Terms of Service

This project calls **private, undocumented Google APIs** (`android.googleapis.com/nova`, `spot-pa.googleapis.com`) and impersonates the official Android Device Manager app (`com.google.android.apps.adm`) by spoofing its package name and certificate fingerprint. This almost certainly violates Google's Terms of Service. Accounts using this tooling may be suspended, and the APIs may break without warning on any Google backend update.

### Credential exposure

All authentication material — the **AAS master token**, GCM device ID, FCM EC private key, and the derived **shared key** (root of the 6-layer E2EE key chain) — is stored in a single plaintext `secrets.json` file. A leaked or accidentally committed `secrets.json` gives an attacker full access to the account's Find My location data. Ensure `secrets.json` is in `.gitignore` and consider encrypting it at rest.

### Intentional bot detection evasion

The dependency `undetected-chromedriver` is a library specifically designed to bypass Google's browser automation detection. Combined with JavaScript injection into live `accounts.google.com` sessions (used during shared key extraction), this places the tool firmly in grey territory from a security standpoint.

### `frida` as a runtime dependency

Frida is a professional dynamic instrumentation / reverse-engineering toolkit. Its presence in `requirements.txt` significantly increases the attack surface of any host running this software. It should not be deployed on shared or production infrastructure.

### Public Grafana dashboard

The current `fly.grafana.toml` enables anonymous viewer access with no authentication. Anyone who discovers the Fly.io URL can view live location data for all tracked devices. Add authentication (`GF_AUTH_ANONYMOUS_ENABLED=false`) before exposing the dashboard beyond a trusted network.

### Privacy

This system tracks physical device locations. It must only be used to track devices that the authenticated Google account owns and that the relevant individuals have consented to being tracked. Tracking a person's device without their knowledge and consent is illegal in most jurisdictions under privacy and stalking laws, regardless of the technical capability to do so.

### API stability

All API endpoints and protobuf schemas used here are reverse-engineered from Google's internal Android apps. They carry no stability guarantee and may change or be shut down by Google at any time without notice.
