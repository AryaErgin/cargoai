# CargoAI – project guide for Claude

Always reply to the user in Turkish. Code, comments, commit messages and docs stay in English.

## What this product is
CargoAI turns freight forwarding brokerage into an AI-driven system: customer requests come in
(email / text), get parsed, priced, sourced from carriers, booked and tracked (4PL/5PL direction).

## Architecture (do not break these rules)
- `app/` – LLM parsers (spot, tender) and email intake. Benchmarked: do NOT change prompts,
  `schemas/`, `evaluation/` or `data/` unless the task explicitly says so; if you do, rerun the evaluators.
- `pricing/` – deterministic quote engine. **No LLM calls in pricing, ever.** Decimal arithmetic only.
- `database/` – shared multi-tenant DB. Every business query is scoped by `tenant_id` via repositories.
  Schema changes need an Alembic migration in `migrations/versions/`.
- `api/` – FastAPI. Fails closed; local demo only on loopback. Never expose buy costs / supplier data to the browser.
- `frontend/` – Next.js App Router + TypeScript + plain CSS, Vitest.
- Secrets (`OPENAI_API_KEY`, `DATABASE_URL`) stay backend-only and are never committed.

## Commands
- Backend tests: `python -m pytest tests -q` (set `OPENAI_API_KEY=offline-test-placeholder` if no key; tests mock the LLM)
- Frontend tests: `cd frontend && npm test -- --run`
- Type check: `cd frontend && npx tsc --noEmit`
- Migrations: `alembic upgrade head`, seed: `python -m database.seed`

## Agent team workflow
For any non-trivial feature, use the agent team in `.claude/agents/`:
1. `architect` writes a plan to `docs/plans/YYYY-MM-DD-<feature>.md` (no code).
2. `backend-developer` and/or `frontend-developer` implement it, task by task.
3. `test-engineer` writes/extends tests and runs the full suite.
4. `code-reviewer` reviews the diff; fix every "must fix" before reporting done.
Never call real LLM, email or carrier APIs in tests – mock them.
