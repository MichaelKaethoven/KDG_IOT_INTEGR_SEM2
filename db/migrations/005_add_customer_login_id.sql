-- Adds a unique customer-facing login identifier so customer login is no
-- longer a password-only scan across every customer row (security plan 10.5).
--
-- The portal login form takes (login_id, password); the lookup is one query on
-- login_id, then a single check_password_hash. login_id is NULL for customers
-- who don't have portal access. A partial unique index keeps NULL allowed but
-- enforces uniqueness for any row that has one.
ALTER TABLE customers
  ADD COLUMN IF NOT EXISTS login_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS customers_login_id_uniq
  ON customers (login_id)
  WHERE login_id IS NOT NULL;
