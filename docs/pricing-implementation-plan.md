# Ocean-FCL pricing implementation plan

Spec: pricing-design.md and the user's detailed request. Execute inline; preserve unrelated workspace changes and protected extraction/frontend files.

- [x] Add failing demo pricing test and protected-file hash baseline.
- [x] Add exchange-rate model/repository, percentage-base field, audit snapshots, migration and demo FX seed.
- [x] Implement typed domain models/errors, exact alias resolvers, direct FX service and centralized Decimal rounding.
- [x] Implement deterministic rate/rule selection and auditable mandatory charge calculations.
- [x] Implement quote orchestration, optional atomic persistence and internal/dev API adapter.
- [x] Add deterministic selection, FX, charge, rule, persistence and API tests; update existing schema expectations for the additive migration.
- [x] Run migrated database/pricing/Python/frontend tests, demo quote, migration drift/offline PostgreSQL checks and protected-file hash comparison; review and document results.

Verification: 117 Python tests and 18 frontend tests passed. Migration 0002 applied to local SQLite; Alembic check reports no drift. Demo engine and API both return buy 3165.00, markup 379.80, sell 3544.80 USD. PostgreSQL offline DDL and migration round trips pass; no local PostgreSQL server is available. SHA-256 hashes of all 21 protected source/data files are unchanged. No OpenAI benchmark calls were made. Independent read-only review found no blockers.

Decisions: user confirmed percentage discount of pre-discount sell. Margin percent uses sell as denominator. Missing and overlapping direct FX both produce MISSING_FX with explicit match details. Optional charges remain unpriced. V1 rejects DG because the rate model cannot express qualified DG applicability. Financial JSON values are decimal strings. Extreme request/storage limits and live PostgreSQL testing are follow-up hardening opportunities.
