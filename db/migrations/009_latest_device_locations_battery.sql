-- 009 — expose battery / source / sats on the latest_device_locations view.
--
-- The Walter PoC resolver writes battery_pct / battery_mv / source / sats into
-- device_locations (db/migrations/008). The trackers list + info view already
-- read the newest fix per device from latest_device_locations (006), but that
-- view only projected lat/lon/accuracy, so the webapp had no cheap way to show
-- the latest battery level without dragging the whole history through the wire.
--
-- Add the PoC columns to the view. Google trackers leave them NULL, so the
-- webapp renders "no battery telemetry" for those and a battery gauge for Walter.
create or replace view latest_device_locations as
select distinct on (device_name)
    device_name, time, lat, lon, accuracy,
    source, sats, battery_mv, battery_pct
from device_locations
order by device_name, time desc;
