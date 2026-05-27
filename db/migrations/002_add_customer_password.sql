-- Adds an optional password hash to customers so they can log into the portal
-- and only see their own orders/trackers.
--
-- SECURITY NOTE: Per product decision, customer login is intentionally
-- password-only (no username/email). On login we walk every customers row and
-- check the password against each row's hash; the first match wins. This means
-- two customers MUST NOT share a password, and timing/oracle attacks are not
-- mitigated. This is acceptable here because the portal is for trusted internal
-- demo use and security is explicitly out of scope. Do NOT use this scheme in
-- a production-facing deployment.
ALTER TABLE customers
  ADD COLUMN IF NOT EXISTS password_hash TEXT;
