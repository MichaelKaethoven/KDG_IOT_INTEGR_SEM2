# Integration Notes

## Database — Supabase / PostgreSQL

The application uses [Supabase](https://supabase.com) as its database backend. Supabase is a managed PostgreSQL service with an HTTP query API (PostgREST) on top. This document explains what is Supabase-specific and what steps are required to migrate to a different database.

---

### What is portable

| Component | Portable? | Notes |
|---|---|---|
| Database schema | ✅ Yes | Plain PostgreSQL — `CREATE TABLE` statements, UUID primary keys, standard column types. Copy the schema to any PostgreSQL host with no changes. |
| Business logic | ✅ Yes | All rules live in the blueprint Python files, not in the DB layer. |
| Templates & frontend | ✅ Yes | No DB awareness whatsoever. |
| Authentication | ✅ Yes | Custom session-based auth — not using Supabase Auth. |
| Grafana dashboards | ✅ Yes | Grafana connects to the PostgreSQL database directly (not through Supabase's API). Point it at any PostgreSQL host by updating the datasource connection string. |

---

### What is Supabase-specific

The webapp and subscriber use the **Supabase Python client** (`supabase-py`), which wraps the PostgREST HTTP API. Its query builder syntax is unique to this client:

```python
# PostgREST query builder — not portable to other DB clients
db.table("customers").select("*").eq("id", x).ilike("name", f"%{q}%").execute().data
db.table("order_trackers").select("id, order:orders!inner(customer_id)").is_("removed_at", "null").execute()
```

The nested join syntax (`order:orders!inner(customer_id)`) is PostgREST-specific.

**Files containing these calls:**

| File | ~Query calls |
|---|---|
| `webapp/blueprints/customers.py` | ~8 |
| `webapp/blueprints/orders.py` | ~12 |
| `webapp/blueprints/trackers.py` | ~8 |
| `webapp/blueprints/dashboard.py` | ~2 |
| `runtime/subscriber.py` | ~2 |
| `webapp/db.py` | client init |

Total: roughly 30–35 query call sites. The Supabase-specific syntax is contained entirely in these files — no other part of the application is affected.

---

### Migration paths

#### Option A — Switch to a different PostgreSQL host (recommended)

Supabase, AWS RDS, Google Cloud SQL, Neon, self-hosted Docker PostgreSQL, and Fly.io Postgres all run standard PostgreSQL. The schema is identical across all of them.

**Steps:**

1. **Export the schema** from Supabase → Database → Migrations, or via `pg_dump --schema-only`.
2. **Import the schema** into the new PostgreSQL instance.
3. **Migrate data** (if any): `pg_dump` / `pg_restore`, or Supabase's built-in export.
4. **Replace the DB client** in `webapp/db.py` and `runtime/subscriber.py`. Replace `supabase-py` with [SQLAlchemy](https://docs.sqlalchemy.org/) (recommended) or `psycopg2`:

   ```python
   # webapp/db.py — SQLAlchemy replacement
   from sqlalchemy import create_engine
   from sqlalchemy.orm import sessionmaker

   engine = create_engine(os.environ["DATABASE_URL"])
   SessionLocal = sessionmaker(bind=engine)

   def get_db():
       return SessionLocal()
   ```

5. **Rewrite query calls** in the 5 blueprint files. Each PostgREST call becomes a SQLAlchemy query or raw SQL. This is mechanical work — the logic and return shapes stay the same. Example:

   ```python
   # Before (Supabase)
   customers = db.table("customers").select("*").ilike("name", f"%{q}%").order("name").execute().data

   # After (SQLAlchemy)
   customers = db.execute(text("SELECT * FROM customers WHERE name ILIKE :q ORDER BY name"), {"q": f"%{q}%"}).mappings().all()
   ```

6. **Update Grafana** datasource: change the host, user, and password in `grafana/provisioning/datasources/`.
7. **Update environment variables**: replace `SUPABASE_URL` / `SUPABASE_KEY` with `DATABASE_URL` (standard PostgreSQL connection string).

**Estimated effort:** 4–8 hours of mechanical query rewriting. No business logic changes.

---

#### Option B — Switch to a different database type (MySQL, MongoDB, etc.)

Not recommended. Reasons:
- The schema uses PostgreSQL-specific types (UUID, TIMESTAMPTZ).
- Grafana's provisioned datasource is configured for PostgreSQL.
- `DISTINCT ON` and other PostgreSQL features are referenced in `development_plan.md` (Phase 3).
- No benefit over Option A for a logistics/tracking workload.

If this is a hard requirement, the schema and all queries must be redesigned from scratch.

---

### Making a future swap easier (optional refactor)

Currently, query calls are scattered across blueprint files. A repository layer would isolate all DB access behind plain Python functions:

```python
# webapp/repository.py
def list_customers(search: str = "") -> list[dict]:
    db = get_db()
    ...

def get_customer(customer_id: str) -> dict:
    db = get_db()
    ...
```

Blueprints would then call `repository.list_customers(search)` with no awareness of the DB client. A DB swap would only require changing `repository.py` and `db.py` — nothing else. This refactor is also the natural place to fix the N+1 query issues noted in Phase 3 of `development_plan.md`.

---

### Environment variables reference

| Variable | Current (Supabase) | After migration (plain PostgreSQL) |
|---|---|---|
| `SUPABASE_URL` | `https://<ref>.supabase.co` | Remove |
| `SUPABASE_KEY` | anon/service role key | Remove |
| `SUPABASE_DB_HOST` | pooler hostname (Grafana) | PostgreSQL host |
| `SUPABASE_DB_USER` | `postgres.<ref>` | PostgreSQL user |
| `SUPABASE_DB_PASSWORD` | database password | database password |
| `DATABASE_URL` | *(not used yet)* | `postgresql://user:pass@host:5432/db` |
