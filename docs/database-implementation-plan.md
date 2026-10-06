# CargoAI Database Implementation Plan

**Goal:** Build the requested storage foundation while preserving extraction behavior.
**Spec:** database-design.md and the user's complete table/validation specification.
**Execution:** inline in the existing workspace; preserve unrelated work, no commits.

- [x] Write database integration tests; verify failure before package exists.
- [x] Implement UUID/UTC base, lazy sessions, 20 models, composite tenant ownership constraints, indexes, and row-based charges.
- [x] Implement tenant/rate/customer/pricing repositories, inclusive candidate lookup, and immutable version cloning; test ownership and history.
- [x] Generate/review a frozen initial Alembic migration; run upgrade, downgrade, schema drift, and PostgreSQL offline compilation checks.
- [x] Add idempotent synthetic seed and safe DB health endpoint; test both success and unavailable state.
- [x] Update dependencies, environment example, ignore rules, and README; run database, existing API, and frontend tests.

Review focus: cross-tenant FK injection; nullable group targeting; date boundaries; concurrent/duplicate versions; UTC round trips; quote-line provenance; missing DATABASE_URL; repeated seeds. Each is covered by integration tests or documented as privileged direct-SQL behavior. Live parser benchmarks will not be rerun because storage does not modify parser paths or require API transmission.

Review outcome: independent read-only review found no blockers. Ensure Session guards register on package import (implemented and tested). Historical status changes currently require successor versions; a later deterministic selection policy will define current-version precedence. PostgreSQL validation is offline DDL only because no local server is available. The seed is atomic and repeatable but intentionally does not repair manually removed demo rows.
