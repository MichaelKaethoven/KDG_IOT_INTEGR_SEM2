-- GoogleFindMyTools — base database schema (PostgreSQL / Supabase)
--
-- Run this ONCE on a fresh database to create every table the application needs.
-- It already includes the columns added by db/migrations/*.sql, so on a fresh
-- install you do NOT also need to run those migration files — they exist only to
-- upgrade databases that were created before those columns were introduced.
--
-- How to apply:
--   • Supabase Studio  → SQL Editor → paste this file → Run
--   • or from a shell  → psql "<your-postgres-connection-string>" -f db/schema.sql

-- gen_random_uuid() lives in the pgcrypto extension (enabled by default on Supabase).
create extension if not exists pgcrypto;

-- Customers -----------------------------------------------------------------
create table if not exists customers (
    id            uuid        primary key default gen_random_uuid(),
    name          text        not null,
    email         text,
    phone         text,
    created_at    timestamptz not null default now(),
    -- Palette index 0..9; the Grafana dashboard maps it to a fixed colour so the
    -- colour an admin picks in the portal is the colour shown on the map.
    color_idx     smallint    not null default 0,
    -- Optional per-customer portal password (Werkzeug hash). DEMO USE ONLY — see
    -- the SECURITY note in db/migrations/002_add_customer_password.sql.
    password_hash text,
    -- Customer-facing login identifier paired with password_hash. NULL for
    -- customers without portal access; unique (case-sensitive) when set.
    login_id      text
);
create unique index if not exists customers_login_id_uniq
    on customers (login_id) where login_id is not null;
create index if not exists customers_name_idx on customers(name);

-- Orders --------------------------------------------------------------------
create table if not exists orders (
    id          uuid        primary key default gen_random_uuid(),
    customer_id uuid        not null references customers(id) on delete cascade,
    status      text        not null default 'pending',   -- pending|active|completed|cancelled
    quantity    integer     not null default 1,
    order_date  timestamptz not null default now(),
    notes       text,
    created_at  timestamptz not null default now()
);
create index if not exists orders_customer_id_idx on orders(customer_id);
create index if not exists orders_status_idx       on orders(status);

-- Trackers ------------------------------------------------------------------
create table if not exists trackers (
    id            uuid        primary key default gen_random_uuid(),
    device_name   text        not null,
    -- Google's canonic_id. POST /trackers/sync upserts on this value.
    serial_number text,
    notes         text,
    created_at    timestamptz not null default now()
);
create index if not exists trackers_device_name_idx   on trackers(device_name);
create index if not exists trackers_serial_number_idx  on trackers(serial_number);

-- Order <-> Tracker assignments (a tracker is "released" by setting removed_at) -
create table if not exists order_trackers (
    id          uuid        primary key default gen_random_uuid(),
    order_id    uuid        not null references orders(id)   on delete cascade,
    tracker_id  uuid        not null references trackers(id) on delete cascade,
    assigned_at timestamptz not null default now(),
    removed_at  timestamptz                                  -- null = currently assigned
);
create index if not exists order_trackers_order_id_idx   on order_trackers(order_id);
create index if not exists order_trackers_tracker_id_idx on order_trackers(tracker_id);
-- Partial index for the "active assignment" filter (removed_at is null), used
-- by every list view that joins/aggregates on currently-assigned trackers.
create index if not exists order_trackers_active_idx
    on order_trackers(removed_at)
    where removed_at is null;

-- Device location history (written by runtime/subscriber.py) ----------------
create table if not exists device_locations (
    id          bigint      generated always as identity primary key,
    device_name text        not null,
    lat         double precision,
    lon         double precision,
    altitude    double precision default 0,
    accuracy    double precision default 0,
    recorded_at timestamptz not null default now(),
    -- Google's reported fix time. The subscriber upserts with
    -- on_conflict="device_name,time", so this pair MUST stay unique.
    time        timestamptz,
    unique (device_name, time)
);
create index if not exists device_locations_device_time_idx
    on device_locations(device_name, time desc);

-- Latest fix per device. The webapp queries this instead of the raw history
-- table on list views so it doesn't drag the full history into memory.
create or replace view latest_device_locations as
select distinct on (device_name)
    device_name, time, lat, lon, accuracy
from device_locations
order by device_name, time desc;

-- Tracker condition log (timeline of dated free-text entries per tracker) ----
-- Separate from the single trackers.notes description field: this is an
-- append-only log for damage reports, battery swaps, firmware updates, etc.
create table if not exists tracker_notes (
    id         uuid        primary key default gen_random_uuid(),
    tracker_id uuid        not null references trackers(id) on delete cascade,
    note       text        not null,
    created_at timestamptz not null default now()
);
create index if not exists tracker_notes_tracker_id_idx
    on tracker_notes(tracker_id, created_at desc);

-- Runtime tuning knobs editable from the portal Settings page ----------------
-- Key/value store read by the webapp (edit) and the middleware (each poll
-- cycle). Missing keys fall back to env/hardcoded defaults in code, so this
-- table can be empty on a fresh install.
create table if not exists app_settings (
    key        text        primary key,
    value      text        not null,
    updated_at timestamptz not null default now()
);
