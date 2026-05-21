-- Run this in the Supabase SQL editor to create the customer/order/tracker tables.

CREATE TABLE trackers (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_name   TEXT UNIQUE NOT NULL,
  serial_number TEXT,
  notes         TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE customers (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name       TEXT NOT NULL,
  email      TEXT,
  phone      TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE orders (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'completed', 'cancelled')),
  quantity    INT NOT NULL CHECK (quantity > 0),
  order_date  TIMESTAMPTZ DEFAULT now(),
  notes       TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE order_trackers (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id    UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  tracker_id  UUID NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
  assigned_at TIMESTAMPTZ DEFAULT now(),
  removed_at  TIMESTAMPTZ
);

-- Enforce: a tracker can only be in one active assignment at a time
CREATE UNIQUE INDEX one_active_assignment
  ON order_trackers (tracker_id)
  WHERE removed_at IS NULL;
