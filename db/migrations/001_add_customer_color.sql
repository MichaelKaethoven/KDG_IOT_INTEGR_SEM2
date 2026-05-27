-- Adds a palette-index column to customers (0..9).
-- The Grafana dashboard maps this index to a fixed color via thresholds,
-- so what the admin picks in the webapp is what shows on the map/table.
ALTER TABLE customers
  ADD COLUMN IF NOT EXISTS color_idx SMALLINT NOT NULL DEFAULT 0;

-- Backfill existing customers with distinct palette slots so they don't all
-- start out red. Admins can change per customer afterwards.
WITH numbered AS (
  SELECT id, (ROW_NUMBER() OVER (ORDER BY id) - 1) % 10 AS new_idx
  FROM customers
)
UPDATE customers c
SET color_idx = n.new_idx
FROM numbered n
WHERE c.id = n.id;
