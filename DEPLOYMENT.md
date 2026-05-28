# GoogleFindMyTools — Deployment & Operations Guide

This is the hand-over guide. It explains, end to end, how to stand the system up
from a fresh clone, how to deploy it to production, and how to run it day to day.
No prior knowledge of the codebase is assumed.

> For the *why* behind the architecture and the reverse-engineered Google layer,
> see [`README.md`](README.md). For swapping the database, see
> [`integration.md`](integration.md). For the original device-listing CLI, see
> [`USAGE.md`](USAGE.md).

---

## Table of contents

1. [What you are deploying](#1-what-you-are-deploying)
2. [Before you start — accounts & tools](#2-before-you-start--accounts--tools)
3. [Repository layout](#3-repository-layout)
4. [One-time setup](#4-one-time-setup)
5. [Run it locally with Docker Compose](#5-run-it-locally-with-docker-compose)
6. [Deploy to production](#6-deploy-to-production)
7. [Using the customer portal](#7-using-the-customer-portal)
8. [The Grafana dashboard](#8-the-grafana-dashboard)
9. [Day-to-day operations](#9-day-to-day-operations)
10. [Environment variable reference](#10-environment-variable-reference)
11. [Troubleshooting](#11-troubleshooting)
12. [Security, privacy & legal](#12-security-privacy--legal)

---

## 1. What you are deploying

The system is **four services** that together poll Google's Find My Device
network for tracker locations, store them, and show them to customers.

| Service | What it does | Default port |
|---|---|---|
| **middleware** | Talks to Google Find Hub, fetches & decrypts locations, publishes them to MQTT. Also exposes `/devices` and `/devicelist`. | 5500 |
| **subscriber** | Listens on MQTT and writes each location into the database. | (none) |
| **webapp** | The Flask customer portal — manage customers, orders, trackers; embeds the map. | 8080 |
| **grafana** | Map & history dashboards, reading the database directly. | 3001 (local) |

```
 Trackers (BLE)
      │  crowdsourced via nearby Android phones
      ▼
 Google Find My Device network
      │  Nova API + FCM push
      ▼
 middleware ──MQTT (TLS)──▶ subscriber ──▶ PostgreSQL (Supabase)
      │                                          │
   webapp ◀── reads ──────────────────────────────┘
      │  embeds
      ▼
 Grafana dashboard
```

You will connect the system to three external things: a **Google account** (the
one paired with the trackers), an **MQTT broker**, and a **PostgreSQL database**
(Supabase). Everything else runs in containers from this repo.

---

## 2. Before you start — accounts & tools

Tick these off first; the setup steps assume they exist.

- [ ] **Docker + Docker Compose** installed (for running the services).
- [ ] **Python 3.10+ and Google Chrome** on the machine you do the *first-time
      Google login* from. The login opens a real Chrome window, so this step
      cannot be done on a headless server.
- [ ] A **Google account** that the trackers are registered to, including its
      password (and 2FA device if enabled).
- [ ] A **Supabase project** (free tier is fine) — <https://supabase.com>.
- [ ] An **MQTT broker**. The free HiveMQ Cloud cluster works out of the box —
      <https://www.hivemq.com/mqtt-cloud-broker/>. You need host, port (8883 for
      TLS), username and password.
- [ ] *(Production only)* A **Fly.io account** and the `flyctl` CLI, **or** a
      Linux host you can run Docker / systemd on.

---

## 3. Repository layout

```
GoogleFindMyTools/
├── runtime/              # middleware.py, subscriber.py, location_fetcher.py
├── webapp/               # Flask portal (app.py, blueprints/, templates/)
├── grafana/provisioning/ # Datasource + dashboard, auto-loaded by Grafana
├── libs/                 # Google auth/crypto/protobuf layer (+ secrets.json lives here)
├── setup/main.py         # One-time Google login / device listing
├── db/
│   ├── schema.sql        # ← run this on a fresh database
│   └── migrations/       # incremental ALTERs for already-existing databases
├── docker-compose.yml    # local + single-host deployment
├── Dockerfile*           # middleware/subscriber, webapp, grafana images
├── fly.*.toml            # Fly.io deployment configs (one per service)
├── findhub.service       # systemd unit for running the middleware on a host
└── .env.example          # copy to .env and fill in
```

---

## 4. One-time setup

Do these steps in order. Steps 4.1–4.2 are done once on a machine with Chrome;
the result (`secrets.json`) is then reused everywhere.

### 4.1 Install dependencies (for the Google login only)

```powershell
cd GoogleFindMyTools
python -m venv venv
.\venv\Scripts\Activate.ps1        # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
```

### 4.2 Authenticate with Google → create `secrets.json`

```powershell
python setup\main.py               # macOS/Linux: python setup/main.py
```

- A Chrome window opens at `accounts.google.com`. **Log in fully** (including
  2FA) to the Google account the trackers belong to.
- On success the script caches all credentials to **`libs/Auth/secrets.json`**
  and prints the devices it found.
- This file is the system's identity to Google. **Keep it secret**, it is
  already in `.gitignore`, and never commit it.

> If login fails or tokens later expire, delete `libs/Auth/secrets.json` and run
> `python setup\main.py` again.

### 4.3 Create the database

1. Create a Supabase project. Note the project **URL** and the **service role
   key** (Project Settings → API).
2. Open **SQL Editor**, paste the contents of [`db/schema.sql`](db/schema.sql),
   and run it. This creates all six tables (`customers`, `orders`, `trackers`,
   `order_trackers`, `device_locations`, `tracker_notes`).
3. From Project Settings → Database, note the **direct connection** host, user
   (`postgres.<project-ref>`) and password — Grafana needs these.

> A fresh database needs only `schema.sql`. The files in `db/migrations/` are for
> upgrading an *older* database that predates newer columns/tables (`color_idx`,
> `password_hash`, the `tracker_notes` table) — skip them on a new install.

#### Using a different database backend

Supabase is just a **managed PostgreSQL host plus the PostgREST HTTP client** —
nothing in the schema or business logic is Supabase-specific. To move to another
PostgreSQL host (AWS RDS, Neon, Fly Postgres, self-hosted Docker, …):

1. Run [`db/schema.sql`](db/schema.sql) on the new host (it is plain PostgreSQL),
   and migrate any existing rows with `pg_dump` / `pg_restore`.
2. Swap the DB client in [`webapp/db.py`](webapp/db.py) and
   [`runtime/subscriber.py`](runtime/subscriber.py) — replace `supabase-py` with
   SQLAlchemy or `psycopg2`, reading a standard `DATABASE_URL`.
3. Rewrite the ~30 PostgREST query calls (the `db.table(...).select(...)` style)
   in the webapp blueprints and the subscriber. This is mechanical — return shapes
   and logic stay the same.
4. Repoint Grafana by editing the `SUPABASE_DB_*` connection in
   `grafana/provisioning/datasources/`.
5. Drop `SUPABASE_URL` / `SUPABASE_KEY` and add `DATABASE_URL`.

> Switching to a non-PostgreSQL engine (MySQL, Mongo, …) is **not** supported —
> the schema and Grafana datasource assume PostgreSQL. Full step-by-step procedure,
> code examples, and an optional repository-layer refactor are in
> [`integration.md`](integration.md).

### 4.4 Create the MQTT broker

Sign up for a broker (e.g. HiveMQ Cloud), create a cluster, and add an access
credential (username + password). Note the **hostname** and **TLS port** (8883).

### 4.5 Generate portal passwords

The portal has two built-in roles whose passwords are stored as **hashes** (never
plaintext). Generate one hash per role:

```powershell
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your-admin-password'))"
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your-viewer-password'))"
```

Copy each full `scrypt:...` string — they go into `ADMIN_PASSWORD_HASH` and
`USER_PASSWORD_HASH`.

> ⚠️ **Footgun:** these hashes contain literal `$` characters. In the `.env` file
> used by Docker Compose, **single-quote** the value
> (`ADMIN_PASSWORD_HASH='scrypt:...'`) or Compose will eat the `$...` segments and
> the login will silently fail. Same rule applies to `flyctl secrets set` from
> PowerShell.

### 4.6 Fill in `.env`

```powershell
cp .env.example .env     # PowerShell: Copy-Item .env.example .env
```

Edit `.env` and fill in every value (full reference in
[section 10](#10-environment-variable-reference)). Minimum to get running:

```ini
# Google polling
POLL_INTERVAL=300

# MQTT broker
MQTT_HOST=your-cluster.s1.eu.hivemq.cloud
MQTT_PORT=8883
MQTT_USER=...
MQTT_PASSWORD=...
MQTT_TOPIC=findmy/devices

# Database (subscriber + webapp)
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_KEY=<service-role-key>

# Database direct connection (Grafana)
SUPABASE_DB_HOST=aws-0-<region>.pooler.supabase.com
SUPABASE_DB_USER=postgres.<project-ref>
SUPABASE_DB_PASSWORD=...

# Portal
SECRET_KEY=<random-long-string>
ADMIN_PASSWORD_HASH='scrypt:...'
USER_PASSWORD_HASH='scrypt:...'

# Grafana iframe URL as seen *by the browser* (see note below)
GRAFANA_URL=http://localhost:3001
GRAFANA_ADMIN_PASSWORD=<grafana-admin-password>
```

> **`GRAFANA_URL` gotcha:** this URL is loaded by the user's *browser*, not by the
> webapp container. When running locally with Docker Compose, Grafana is published
> on host port **3001**, so set `GRAFANA_URL=http://localhost:3001` (the
> `.env.example` default of `:3000` will show an empty map locally). In production,
> set it to the public Grafana URL.

---

## 5. Run it locally with Docker Compose

With `.env` filled in and `libs/Auth/secrets.json` present:

```powershell
docker compose up --build
```

This starts all four services. Then:

| Service | URL |
|---|---|
| Customer portal | <http://localhost:8080> |
| Grafana | <http://localhost:3001> (admin login: `admin` / `GRAFANA_ADMIN_PASSWORD`) |
| Middleware API | <http://localhost:5500/devices> |

First login to the portal at <http://localhost:8080/login> with your **admin**
password. The middleware mounts `./libs/Auth` into the container, so the
`secrets.json` you created in step 4.2 is picked up automatically.

Stop with `Ctrl+C`; `docker compose down` removes the containers (the
`grafana_data` volume persists dashboard state).

---

## 6. Deploy to production

Two supported paths. **Fly.io** (used by this project) is the simplest.

### Option A — Fly.io (three apps)

The repo ships three Fly configs — one per deployable service:

| Config | App |
|---|---|
| `fly.toml` | middleware **and** subscriber (two processes, one app) |
| `fly.webapp.toml` | the portal |
| `fly.grafana.toml` | Grafana |

**1. Create the apps and a volume for the Google credentials.** The middleware
needs a persistent place for `secrets.json`:

```powershell
flyctl apps create findmy-middleware-...      # or use the names in the toml files
flyctl volumes create auth_data --region ams --size 1 --app findmy-middleware-...
```

`fly.toml` mounts that volume at `/app/auth_data`. Tell the auth layer to use it
by setting the `SECRETS_PATH` secret (see below); then upload your local
`secrets.json` onto the volume (e.g. via `flyctl ssh sftp shell` or a one-off
machine) at `/app/auth_data/secrets.json`.

**2. Set secrets** (these are *secrets*, not the plaintext `.env`):

```powershell
# middleware / subscriber app
flyctl secrets set --app findmy-middleware-... `
  MQTT_HOST=... MQTT_USER=... MQTT_PASSWORD=... MQTT_TOPIC=findmy/devices `
  SUPABASE_URL=... SUPABASE_KEY=... SECRETS_PATH=/app/auth_data/secrets.json

# webapp
flyctl secrets set --app findmy-webapp `
  SUPABASE_URL=... SUPABASE_KEY=... SECRET_KEY=... `
  ADMIN_PASSWORD_HASH='scrypt:...' USER_PASSWORD_HASH='scrypt:...' `
  GRAFANA_URL=https://findmy-grafana.fly.dev

# grafana
flyctl secrets set --app findmy-grafana `
  SUPABASE_DB_HOST=... SUPABASE_DB_USER=... SUPABASE_DB_PASSWORD=...
```

> Single-quote the password-hash values (PowerShell `$` footgun, see 4.5). Secret
> **names must match the code** exactly (`ADMIN_PASSWORD_HASH`, not
> `ADMIN_PASSWORD`).

**3. Deploy each app:**

```powershell
flyctl deploy --config fly.toml         --app findmy-middleware-...
flyctl deploy --config fly.webapp.toml  --app findmy-webapp
flyctl deploy --config fly.grafana.toml --app findmy-grafana
```

The webapp reaches the middleware over Fly's private network — `fly.webapp.toml`
already sets `MIDDLEWARE_URL` to the middleware's `.internal` address. Health
checks hit `/healthz` (middleware) and `/login` (webapp).

> ⚠️ `fly.grafana.toml` enables **anonymous viewer access**
> (`GF_AUTH_ANONYMOUS_ENABLED=true`) so the portal's embedded map renders without
> a separate Grafana login. The trade-off is that **anyone with the Grafana URL
> can see live locations**. Read [section 8](#8-the-grafana-dashboard) for how to
> keep it private and the options for locking it down.

### Option B — Single Linux host (systemd + Docker)

1. Copy the repo, `.env`, and `libs/Auth/secrets.json` to the host.
2. For the full stack, just run `docker compose up -d --build` on the host.
3. To run only the middleware as a native service instead, install the provided
   unit: `findhub.service` runs `middleware.py` as the `findhub` user from
   `/opt/findhub`, loads `/opt/findhub/.env`, and restarts on failure. Adjust the
   paths in the unit file, then `systemctl enable --now findhub`.

---

## 7. Using the customer portal

Open the portal and log in at `/login`. There is **one password field**; which
password you type decides your role:

| Role | How they log in | Can do |
|---|---|---|
| **admin** | `ADMIN_PASSWORD_HASH` password | Everything: create/edit/delete customers, orders, trackers; sync; change order status. |
| **user** | `USER_PASSWORD_HASH` password | Read-only view of all customers, orders, trackers and the map. |
| **customer** | a per-customer password set on the customer record | Sees only *their own* orders, trackers and map. |

### Customers
`Customers` tab → **New** (admin). Set name, optional email/phone, a **colour**
(used on the map), and optionally a **password** so that customer can log in and
see only their own data.

### Trackers
`Trackers` tab lists every tracker with columns for **Status**, **With customer**,
**In order** and **Last seen at**.

- **Staleness:** a tracker that hasn't reported a location in the last
  `TRACKER_STALE_HOURS` (default **24**, see [section 10](#10-environment-variable-reference))
  is highlighted **red** with a `stale` badge (or `Never` if it has never pinged).
  Use the **No ping > Nh** toggle above the table to show only stale trackers; the
  toggle carries a live count. This replaces the email-alert idea — staleness is
  surfaced in the UI instead of pushed.
- **Condition log:** open a tracker's **Edit** page to see its condition log — a
  reverse-chronological timeline of dated free-text notes (damage, battery swaps,
  firmware updates). Admins add entries from the same page. This is separate from
  the single free-text *Notes* field on the tracker.
- **Sync from Google** (admin button): pulls the live device list from the
  middleware and upserts trackers, matching on Google's `canonic_id`
  (stored as `serial_number`). Run this whenever devices are added/renamed in
  Google Find Hub. *(Requires the middleware to be reachable — it is, in Docker
  and on Fly.)*
- You can also add/edit trackers manually.

### Orders & their lifecycle
`Orders` tab → **New** (admin): pick a customer and a quantity. An order moves
through a fixed state machine:

```
pending ──▶ active ──▶ completed
   │           │
   └────────┬──┴──▶ cancelled
```

Once an order reaches **completed** or **cancelled** it is *closed* (no further
edits). Moving an order to a terminal state shows a **confirmation page** that
lists the trackers still attached; confirming **automatically releases** them so
they become available for other orders.

- **Assign / remove trackers** from the order detail page. You can select
  multiple at once. Only trackers not currently assigned elsewhere are offered.

### Dashboard
The `Dashboard` tab embeds the Grafana map, filtered by the customer / order /
tracker you select, with a **current vs. historical** toggle. Customer logins are
pinned to their own data automatically.

- **Live** view shows each tracker's latest position.
- **Historical** view plays back the path each tracker took. In this mode a
  **time-range selector** appears (Last 1h / 6h / 24h / 7d / 30d / 90d); changing
  it redraws the playback for that window. The range is passed to the Grafana
  iframe as `from`/`to`, so the embedded map reflects it without needing Grafana's
  own (kiosk-hidden) time picker.

---

## 8. The Grafana dashboard

Grafana is **provisioned automatically** — you do not build dashboards by hand:

- **Datasource** (`grafana/provisioning/datasources/supabase.yaml`) points at the
  PostgreSQL database using the `SUPABASE_DB_*` variables.
- **Dashboard** (`grafana/provisioning/dashboards/trackers.json`) is loaded on
  startup. It is locked (`disableDeletion`, `allowUiUpdates: false`) so the portal
  iframe URL stays stable. To edit it, log in as the Grafana admin, change it, and
  export the JSON back into that file.
- **Customer colours**: the `color_idx` on each customer maps to a fixed palette
  slot in `trackers.json`. The palette in `webapp/blueprints/customers.py`
  (`CUSTOMER_PALETTE`) and the dashboard thresholds must stay in lock-step — if
  you add a colour in one place, add it in the other.

The portal embeds the dashboard at
`/d/tracker-locations/tracker-dashboard` with `var-*` filters; keep that dashboard
UID/slug if you replace the JSON.

### How the embedded map authenticates — and what you need to do

The portal **server never connects to Grafana**. It only builds an `<iframe>` URL
(see `webapp/blueprints/dashboard.py`); the actual request to Grafana is made by
the **viewer's browser**. So whether the map renders comes down to how Grafana
authenticates that browser request:

- **On Fly (`fly.grafana.toml`)**, anonymous **Viewer** access is enabled, so the
  iframe loads with no login. This is what makes the embed "just work" — at the
  cost of the dashboard being viewable by anyone who has the Grafana URL.
- **In local Docker Compose**, anonymous access is **off**. The embed then only
  renders if the browser already has a logged-in Grafana session — sign in once at
  <http://localhost:3001> (admin / `GRAFANA_ADMIN_PASSWORD`) and it works for the
  rest of the session (portal and Grafana are both `localhost`, so the cookie is
  shared).

**To run it properly, pick one of these:**

1. **Keep anonymous on, but don't make the URL public.** Fine for a demo or an
   internal/VPN deployment. Treat the Grafana URL as a secret and don't link to it
   publicly. Simplest, zero extra work — this is the shipped default.
2. **Serve the portal and Grafana on one parent domain** (recommended for
   production). E.g. `app.yourdomain.com` (portal) and `grafana.yourdomain.com`
   (Grafana). Because they share the registrable domain `yourdomain.com`, set
   `GF_AUTH_ANONYMOUS_ENABLED=false` and a logged-in Grafana session cookie is
   sent to the iframe as a first-party cookie (`SameSite=Lax`). Viewers log into
   Grafana once. Set `GRAFANA_URL` to the `grafana.` host.
3. **Auth proxy** (`GF_AUTH_PROXY`). Put Grafana behind a reverse proxy that
   injects an authenticated header so the iframe needs no interactive login at all.
   Most work, fully seamless and private.

> ⚠️ **Don't** simply set `GF_AUTH_ANONYMOUS_ENABLED=false` on two separate
> `*.fly.dev` apps and expect the embed to work. `fly.dev` is a public suffix, so
> `findmy-webapp.fly.dev` and `findmy-grafana.fly.dev` are *different sites*; the
> Grafana cookie becomes third-party and modern browsers block it. You'd also need
> `GF_SECURITY_COOKIE_SAMESITE=none` and third-party cookies allowed — fragile.
> Use option 2 or 3 instead.

---

## 9. Day-to-day operations

**Polling cadence.** The middleware polls every `POLL_INTERVAL` seconds (default
300; Google's practical floor). Lower values risk rate-limiting / account flags.

**Re-authenticating with Google.** Tokens in `secrets.json` eventually expire (or
break after an E2EE reset). Symptom: middleware logs `401`/decrypt errors and no
new locations arrive. Fix: regenerate `secrets.json` (step 4.2) on a Chrome
machine and replace it — locally it is the mounted `libs/Auth/secrets.json`; on
Fly, replace the file on the `auth_data` volume and restart the middleware.

**Logs.**
- Docker: `docker compose logs -f middleware` (or `subscriber` / `webapp`).
- Fly: `flyctl logs --app <app-name>`.
Healthy middleware logs show `[poll] got N location record(s)` and
`[mqtt] published N device(s)`; the subscriber logs `[supabase] upserted ...`.

**Backups.** The valuable state is the Supabase database. Use Supabase's
scheduled backups, or `pg_dump` on a cron. Grafana's `grafana_data` volume only
holds UI state (the dashboard is re-provisioned from the repo).

**Adding trackers.** Pair the device in Google Find Hub, then click **Sync from
Google** in the portal.

---

## 10. Environment variable reference

| Variable | Used by | Required | Notes |
|---|---|---|---|
| `POLL_INTERVAL` | middleware | no (300) | Seconds between Google polls. |
| `PORT` | middleware | no (5500) | Middleware HTTP port. |
| `MQTT_HOST` | middleware, subscriber | **yes** | Broker hostname. |
| `MQTT_PORT` | middleware, subscriber | no (8883) | TLS port. |
| `MQTT_USER` / `MQTT_PASSWORD` | middleware, subscriber | **yes** | Broker credentials. |
| `MQTT_TOPIC` | middleware, subscriber | no (`findmy/devices`) | Base topic. |
| `SUPABASE_URL` | subscriber, webapp | **yes** | `https://<ref>.supabase.co`. |
| `SUPABASE_KEY` | subscriber, webapp | **yes** | Service role key. |
| `SUPABASE_DB_HOST` | grafana | **yes** | Direct PostgreSQL host (pooler). |
| `SUPABASE_DB_USER` | grafana | **yes** | `postgres.<ref>`. |
| `SUPABASE_DB_PASSWORD` | grafana | **yes** | Database password. |
| `SECRET_KEY` | webapp | **yes** | Flask session signing key — random & secret. |
| `ADMIN_PASSWORD_HASH` | webapp | **yes** | Werkzeug hash; single-quote it. |
| `USER_PASSWORD_HASH` | webapp | **yes** | Werkzeug hash; single-quote it. |
| `WEBAPP_PORT` | webapp | no (8080) | Portal port. |
| `TRACKER_STALE_HOURS` | webapp | no (24) | Hours without a ping before a tracker is flagged stale (red) in the Trackers list. |
| `GRAFANA_URL` | webapp | **yes** | Browser-reachable Grafana URL (local: `:3001`). |
| `MIDDLEWARE_URL` | webapp | no | Where the portal calls `/devicelist`. Docker: `http://middleware:5500`. |
| `GRAFANA_ADMIN_PASSWORD` | grafana | no (`admin`) | Grafana admin login. |
| `SECRETS_PATH` | middleware | no | Override path to `secrets.json` (set on Fly to the volume path). |

---

## 11. Troubleshooting

| Symptom | Likely cause & fix |
|---|---|
| Chrome never closes during `setup/main.py` | Finish the full Google sign-in (incl. 2FA); it waits up to ~5 min for the OAuth cookie. |
| Middleware logs `401` / "Failed to decrypt" | Google tokens expired or E2EE was reset. Delete `libs/Auth/secrets.json`, re-run step 4.2, redeploy the file. |
| Portal login always says "Invalid password" | The hash in `.env` was truncated by `$` expansion — **single-quote** the value (4.5). Also confirm `SECRET_KEY` is set. |
| Dashboard tab shows a blank box | `GRAFANA_URL` doesn't match where the browser can reach Grafana (use `:3001` locally), or Grafana embedding is blocked. |
| `Could not reach middleware ...` on Sync | Middleware not running / `MIDDLEWARE_URL` wrong. In Docker it should be `http://middleware:5500`. |
| No rows in `device_locations` | Check the subscriber logs; verify `SUPABASE_URL/KEY` and that MQTT creds match the middleware's. |
| Grafana map empty but DB has rows | Datasource creds (`SUPABASE_DB_*`) wrong, or no trackers assigned to the selected customer/order. |

---

## 12. Security, privacy & legal

This system uses **private, undocumented Google APIs** and stores powerful
credentials. Read the full risk section in [`README.md`](README.md#safety-concerns--risks).
The essentials:

- **`secrets.json` is the keys to the kingdom.** It grants full access to the
  account's location data. Keep it off git (already gitignored), restrict file
  permissions, and consider encrypting it at rest.
- **The Fly Grafana is anonymous-viewer by default** so the embedded map works
  without a login — which means anyone with its URL can see live locations. Keep
  the URL private, or lock it down using one of the options in
  [section 8](#8-the-grafana-dashboard) (single parent domain + login, or an auth
  proxy). Local Compose already runs Grafana with a login required.
- **Customer password login is demo-grade only** (password-only, first-match — see
  `db/migrations/002_add_customer_password.sql`). Do not rely on it for real
  multi-tenant isolation; two customers must never share a password.
- **Privacy & consent.** Only track devices the Google account owns and that the
  people carrying them have consented to. Covert tracking is illegal in most
  jurisdictions regardless of technical capability.
- **API stability.** Google can change or block these endpoints at any time, and
  using them may violate Google's Terms of Service.

---

### Where to go next

- [`development_plan.md`](development_plan.md) — remaining Phase 8 ideas.
- [`integration.md`](integration.md) — moving off Supabase to another PostgreSQL
  host or DB.
- [`README.md`](README.md) — deep dive on the Google integration internals.
