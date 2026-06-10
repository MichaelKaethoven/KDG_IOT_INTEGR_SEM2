-- 008 — extra location columns for the Walter PoC asset tracker.
--
-- The Walter resolver (walter/backend/resolver/app.py) now writes into
-- device_locations instead of its own asset_locations table, so the PoC device
-- shows up in the customer portal trackers list and the main Grafana dashboards
-- like any Google tracker. device_locations had no place for the PoC's
-- source / battery / satellite data, so add them here.
--
-- All nullable: the parent subscriber (runtime/subscriber.py) never sets them,
-- and Google trackers simply leave them NULL.
alter table device_locations add column if not exists source      text;     -- gnss | wifi | cell | none
alter table device_locations add column if not exists sats        integer;
alter table device_locations add column if not exists battery_mv  integer;
alter table device_locations add column if not exists battery_pct integer;

-- Allow rows with no resolved location: a Walter cycle where GNSS failed and the
-- fallback didn't resolve still reports battery + a "none" source, so the device
-- registers a heartbeat (staleness/last_seen) without coordinates. The Grafana
-- geomap already filters `lat IS NOT NULL`. (schema.sql already has these
-- nullable; this realigns databases created with the old NOT NULL constraint.)
alter table device_locations alter column lat drop not null;
alter table device_locations alter column lon drop not null;
