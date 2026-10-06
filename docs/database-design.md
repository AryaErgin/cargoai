# CargoAI shared database design

Implement the user-specified 20-table shared database as an independent SQLAlchemy package. Existing parser behavior and public parse endpoints stay stateless. Production uses PostgreSQL/psycopg; local tests use SQLite with foreign keys enabled. All IDs are UUIDs and application timestamps are UTC.

Business rows carry tenant_id. Composite tenant/id foreign keys prevent references to another tenant's supplier, group, rate, customer, import, or quote. Global locations, equipment, and charge types are shared reference data. Nullable tenant aliases allow global and private vocabularies. Quote lines and group members also carry tenant_id so their ownership is enforceable.

Repositories require an explicit tenant UUID for every business operation. There is no unscoped business listing and no CRUD API. Service methods flush but callers own commit/rollback. Candidate lookup includes group membership and inclusive validity windows, but does not rank, convert currency, or calculate prices.

Rate updates create a new sheet version and copied rate/charge snapshots with new UUIDs. Persisted sheet/rate/charge objects cannot be changed or deleted through ORM sessions. Draft population remains possible through new inserts. Foreign keys use restrictive deletion to preserve quote provenance. Direct SQL is privileged infrastructure access, not a tenant-facing interface; authentication/RLS policy selection is deferred until an authenticated tenant context exists.

Alembic's initial migration is a frozen table definition, independent of later model changes. SQLite migration round-trips, PostgreSQL offline DDL, and metadata drift checks are tested. Database health initializes lazily and exposes only connection status. Demo seed is explicit, repeatable, and clearly marked synthetic.

Non-goals: pricing execution, authentication, upload/import execution, parser changes, frontend changes, production deployment, automatic text persistence.
