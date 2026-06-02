-- Indexes on columns the webapp filters/sorts by but didn't have an index for
-- (security plan 10.10). All four are small B-trees; safe to apply online.
--
-- - orders.status                : list view filters by status
-- - order_trackers.removed_at    : every list view filters active assignments
--                                  (removed_at IS NULL) — a partial index keeps
--                                  the active subset tiny and fast.
-- - trackers.serial_number       : sync upserts match on this
-- - customers.name               : list view sorts and ILIKE-searches on this
CREATE INDEX IF NOT EXISTS orders_status_idx
    ON orders (status);

CREATE INDEX IF NOT EXISTS order_trackers_active_idx
    ON order_trackers (removed_at)
    WHERE removed_at IS NULL;

CREATE INDEX IF NOT EXISTS trackers_serial_number_idx
    ON trackers (serial_number);

CREATE INDEX IF NOT EXISTS customers_name_idx
    ON customers (name);
