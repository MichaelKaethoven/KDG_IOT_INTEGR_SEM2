-- Adds a per-tracker condition/notes log: a timeline of dated free-text entries
-- (damage reports, battery swaps, firmware updates, …). This is separate from
-- the single trackers.notes description column, which stays as-is.
--
-- Fresh installs get this table from db/schema.sql; this migration only exists to
-- upgrade databases created before tracker_notes was introduced.
create table if not exists tracker_notes (
    id         uuid        primary key default gen_random_uuid(),
    tracker_id uuid        not null references trackers(id) on delete cascade,
    note       text        not null,
    created_at timestamptz not null default now()
);
create index if not exists tracker_notes_tracker_id_idx
    on tracker_notes(tracker_id, created_at desc);
