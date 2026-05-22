# GoogleFindMyTools — Project Context

> **INSTRUCTION FOR CLAUDE:** After completing any development task, update the Phase Status table below (mark ✅ Done). Update Key Files if new files are added. This file is always loaded into context — keep it accurate so the project never needs to be re-explored.

---

## Architecture

Four Docker services communicating via MQTT and Supabase:

| Service | Entry point | Role |
|---|---|---|
| `middleware` | `runtime/middleware.py` | Polls Google Find Hub (FCM), publishes device locations to MQTT broker |
| `subscriber` | `runtime/subscriber.py` | Subscribes to MQTT, upserts device locations into Supabase |
| `webapp` | `webapp/app.py` | Flask customer portal — Customer/Order/Tracker CRUD, Grafana iframe embed |
| `grafana` | Grafana 11.0.0 image | Location dashboards reading Supabase PostgreSQL directly |

The middleware and subscriber share one Docker image (`Dockerfile`). The webapp uses `Dockerfile.webapp`. Grafana uses `Dockerfile.grafana`.

---

## Key Files

### `webapp/`
| File | Purpose |
|---|---|
| `app.py` | Flask application factory. Registers all blueprints; inits `csrf` and `limiter` from `extensions.py`. |
| `extensions.py` | Shared extension instances: `CSRFProtect` (csrf) and `Limiter` (limiter, 200/day default). Import these here to avoid circular imports. |
| `db.py` | Supabase client singleton (`get_db()`). |
| `requirements.txt` | Flask, supabase, flask-wtf, Flask-Limiter, gunicorn. |
| `blueprints/auth.py` | Login/logout, `login_required` / `admin_required` decorators. Rate-limited to 10 login attempts/min. |
| `blueprints/customers.py` | Customer list, detail, new, edit, delete. |
| `blueprints/orders.py` | Order list, detail, new, edit, delete, tracker assign/remove. |
| `blueprints/trackers.py` | Tracker list, new, edit, delete. |
| `blueprints/dashboard.py` | Dashboard view with embedded Grafana iframe. |
| `templates/base.html` | Base layout with Bootstrap 5 nav. |
| `templates/login.html` | Standalone login page (not extending base). |
| `templates/customers/` | list, form, detail templates. |
| `templates/orders/` | list, form, detail templates. |
| `templates/trackers/` | list, form templates. |

### `runtime/`
| File | Purpose |
|---|---|
| `middleware.py` | Flask app on port 5500. Exposes `/devices`. Runs the polling loop: calls `fetch_all_locations()`, publishes to MQTT. |
| `subscriber.py` | Connects to MQTT, calls `_upsert()` on each message to write to Supabase. |
| `location_fetcher.py` | All Google Find Hub / FCM logic: `fetch_device_list()`, `fetch_locations_for_device()`, `fetch_all_locations()`, protobuf decoding/decryption. |

### `libs/`
Vendor libraries for Google FCM, crypto, protobuf decoding. Mounted as volume in `middleware` container.

### Infrastructure
| File | Purpose |
|---|---|
| `docker-compose.yml` | All service definitions, env var wiring. |
| `Dockerfile` | middleware + subscriber image (Python 3.11-slim). |
| `Dockerfile.webapp` | webapp image. |
| `Dockerfile.grafana` | Grafana with extra plugins. |
| `grafana/provisioning/dashboards/dashboard.yaml` | Dashboard provisioning config. `disableDeletion: true`, `allowUiUpdates: false`. |
| `grafana/provisioning/datasources/` | Supabase PostgreSQL datasource config. |
| `.env.example` | Template for all required env vars. |
| `.github/workflows/fly-deploy.yml` | CI/CD to Fly.io. |

---

## Auth & Security Model

- Two roles: `admin` (full CRUD) and `user` (read-only).
- Passwords stored as **Werkzeug hashes** in env: `ADMIN_PASSWORD_HASH`, `USER_PASSWORD_HASH`.
- Generate: `python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('yourpassword'))"`
- Login rate-limited: 10 attempts/minute per IP via Flask-Limiter.
- All POST forms protected with CSRF tokens via Flask-WTF (`{{ csrf_token() }}`).
- `admin_required` redirects unauthenticated users to `/login`; returns 403 only for authenticated non-admins.
- Open redirect blocked: `next=` param is rejected if it contains a netloc (absolute URL).
- Grafana: anonymous access disabled (`GF_AUTH_ANONYMOUS_ENABLED=false`). Port 3001 still exposed for admin dashboard editing (requires Grafana login).

---

## Phase Status

| Phase | Item | Status |
|---|---|---|
| 1 | 1.1 Fix open redirect after login | ✅ Done |
| 1 | 1.2 Restrict Grafana anonymous access | ✅ Done |
| 1 | 1.3 CSRF protection on all POST forms | ✅ Done |
| 1 | 1.4 Hash stored passwords | ✅ Done |
| 1 | 1.5 Brute-force protection on login | ✅ Done |
| 1 | 1.6 Fix `admin_required` redirect | ✅ Done |
| 2 | 2.1 Fix broken test_supabase.py import | ⬜ Todo |
| 2 | 2.2 Fix division-by-zero (quantity=0) | ⬜ Todo |
| 2 | 2.3 Fix Supabase client per-message | ⬜ Todo |
| 2 | 2.4 Fix int() crash on bad quantity input | ⬜ Todo |
| 3 | 3.1 Eliminate N+1 queries in list views | ⬜ Todo |
| 3 | 3.2 Parallel device location fetching | ⬜ Todo |
| 3 | 3.3 Replace busy-wait with threading.Event | ⬜ Todo |
| 4 | 4.1 Fix deprecated utcfromtimestamp | ⬜ Todo |
| 4 | 4.2 Switch middleware to gunicorn | ⬜ Todo |
| 4 | 4.3 Fix db.py singleton thread-safety | ⬜ Todo |
| 4 | 4.4 Remove sys.path.insert hacks | ⬜ Todo |
| 5 | 5.1 Fix incorrect depends_on for subscriber | ⬜ Todo |
| 5 | 5.2 Run containers as non-root | ⬜ Todo |
| 5 | 5.3 Add healthchecks | ⬜ Todo |
| 5 | 5.4 Pin base image digests | ⬜ Todo |
| 6 | 6.1 Convert test scripts to pytest | ⬜ Todo |
| 6 | 6.2 Add unit tests for crypto/MQTT paths | ⬜ Todo |
| 7 | 7.1 Auto-sync trackers from Google Find Hub | ⬜ Todo |
| 7 | 7.2 Mass assign / remove trackers | ⬜ Todo |
| 7 | 7.3 Order lifecycle state machine | ⬜ Todo |
| 8 | 8.1–8.6 Additional suggestions | ⬜ Todo |
