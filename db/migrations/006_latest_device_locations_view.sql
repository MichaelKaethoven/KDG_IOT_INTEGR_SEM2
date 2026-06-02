-- Surfaces the most recent fix per device as a view, so the trackers list page
-- can ask for one row per device instead of pulling the entire location
-- history just to keep the newest in Python (security plan 10.8).
--
-- The existing (device_name, time desc) index already makes this DISTINCT ON
-- a single index scan, so the view is essentially free at query time.
CREATE OR REPLACE VIEW latest_device_locations AS
SELECT DISTINCT ON (device_name)
    device_name,
    time,
    lat,
    lon,
    accuracy
FROM device_locations
ORDER BY device_name, time DESC;
