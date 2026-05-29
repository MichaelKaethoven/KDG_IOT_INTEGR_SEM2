-- Adds a key/value store for runtime tuning knobs editable from the portal
-- Settings page (poll interval, location batch size/delay/timeout, tracker
-- stale hours). The webapp writes it; the middleware reads it each poll cycle.
-- Missing keys fall back to env/hardcoded defaults in code, so this table may
-- legitimately stay empty.
--
-- Fresh installs get this table from db/schema.sql; this migration only exists
-- to upgrade databases created before app_settings was introduced.
create table if not exists app_settings (
    key        text        primary key,
    value      text        not null,
    updated_at timestamptz not null default now()
);
