# CargoAI

CargoAI is an experimental alpha for extracting structured shipment details from freight requests. It supports Spot RFQs and Freight Tender lane entries using GPT-6 Luna with OpenAI Structured Outputs. Extracted information must be reviewed before operational use.

## Current benchmark results

- Spot development: **260/260 fields (100.00%)**
- Public validation: **635/650 fields (97.69%)** (latest measured)
- Real company tender: **112/112 fields (100.00%)**, identical across three runs

## Project structure

```text
app/          Spot and tender parser modules
api/          FastAPI backend
frontend/     Next.js web interface
evaluation/   Benchmark evaluators
schemas/      Structured output schemas
data/         Benchmark datasets
database/     Multi-tenant storage and repositories
migrations/   Alembic database migrations
pricing/      Deterministic ocean-FCL quote engine
```

## Setup

Create and activate a Python virtual environment, then install backend dependencies:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Create a root `.env` file with your OpenAI API key and local frontend origin:

```text
OPENAI_API_KEY=your_api_key_here
CARGOAI_FRONTEND_ORIGIN=http://localhost:3000
DATABASE_URL=sqlite:///./cargoai.db
```

Keep API keys private; never commit them to Git. The frontend uses `NEXT_PUBLIC_API_BASE_URL` in `frontend/.env.local`:

```text
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Start the backend from the repository root:

```bash
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000 --no-proxy-headers
```

In a second terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open the frontend at [http://localhost:3000](http://localhost:3000). The backend is at [http://127.0.0.1:8000](http://127.0.0.1:8000), with the health endpoint at `/health`.

## API

- `POST /parse/spot` — extract fields from a Spot RFQ
- `POST /parse/tender` — extract fields from a Freight Tender

The public demo processes submitted text for extraction and does not persist it. Spot extraction now opens an editable shipment review form and can calculate a deterministic quote in explicitly configured local demo mode. Booking, tracking, customs automation, and Excel upload are not available.

## Database

CargoAI uses one shared multi-tenant database. New logistics companies do not receive separate codebases or databases by default. Rates, suppliers, aliases, customers, pricing rules, and import mappings are scoped by `tenant_id`; locations, equipment types, and charge types can be shared. Tenant-scoped repositories and composite ownership foreign keys prevent cross-tenant business references. Database connections are lazy, so existing parsing does not require database setup.

For local development, set `DATABASE_URL=sqlite:///./cargoai.db`. Production targets PostgreSQL using `DATABASE_URL=postgresql+psycopg://user:password@host:5432/cargoai`. Never commit database files or credentials.

Apply migrations, then optionally load synthetic demo values:

```bash
alembic upgrade head
python -m database.seed
```

For future model changes, generate and review a migration before applying it:

```bash
alembic revision --autogenerate -m "..."
```

Rates and charges retain separate historical versions. Use `create_rate_sheet_version` to copy a sheet with new rate/charge IDs; existing quote lines retain their original references and stored amounts. Repository methods flush changes; callers commit or roll back their unit of work. Privileged direct SQL is outside the tenant service boundary. There is no public database CRUD API; `GET /health/db` reports connectivity only.

Future onboarding: create tenant → import rates → map columns once → save import profile → configure pricing → start quoting. Import profiles support reusable mappings; import execution is not implemented.

Run local tests without sending RFQs to the API:

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
cd frontend
npm test -- --run
```

## Pricing engine

Structured RFQ → location/equipment resolver → rate selector → charge calculator → FX conversion → pricing rules → quote.

The engine is shared across tenants; rates, FX, and pricing rules are company-specific tenant data. V1 supports `OCEAN_FCL`, `20GP`/`40GP`/`40HC`, and per-container, per-shipment, flat, and explicitly configured percentage charges. It uses Decimal arithmetic with high-precision intermediates and two-decimal `ROUND_HALF_UP` monetary results. Buy total sums rounded mandatory charge lines; optional charges are reported separately. There are no LLM, carrier, or live FX calls in pricing.

Rates rank by exact/exact → exact/group → group/exact → group/group, then priority, narrower effective validity, later validity start, higher sheet version, and newest rate creation time. Unresolved ties fail. Rules rank by customer, lane, and equipment specificity, then priority. One primary markup, one minimum-margin floor, and one discount may apply; competing ties fail. Discount is a percentage of sell after markup/minimum-margin. Margin percent is final margin divided by sell total.

FX requires one direct stored tenant rate valid on the effective date; identical currencies explicitly use 1. Missing or overlapping FX fails. Percentage-charge bases must be stored as `FREIGHT_SUBTOTAL` or `BUY_SUBTOTAL`, excluding percentage charges themselves. Fixed markup and minimum margin require an explicit currency. V1 rejects dangerous goods because the rate schema has no DG qualification.

Apply the new migration and rerun the demo seed to add synthetic FX examples:

```bash
alembic upgrade head
python -m database.seed
```

Local demo endpoint: `POST /quote/spot`. Legacy structured RFQs remain supported; reviewed shipment IDs are preferred. Example legacy body:

```json
{
  "tenant_id": "<tenant UUID>",
  "rfq": {
    "origin": "Shanghai",
    "destination": "Ambarli",
    "container_type": "40HC",
    "container_count": 2,
    "dangerous_goods": false
  },
  "effective_date": "2026-10-15",
  "requested_currency": "USD",
  "persist": false
}
```

The engine calculates buy **3165.00 USD**, markup **379.80 USD**, and sell **3544.80 USD**. The HTTP response exposes customer sell amounts only. Buy costs, supplier details, and rule/markup metadata remain in internal engine results and historical audit snapshots. `persist` defaults to false; explicit persistence retains original rate/charge references. No authenticated internal user exists yet, so rate administration HTTP routes are disabled (403).

## Local RFQ-to-pricing workflow

There is no authentication. Pricing and lookups fail closed unless `CARGOAI_LOCAL_DEMO=1` and `CARGOAI_DEMO_TENANT_ID` identifies the active seeded `demo-forwarder`. A caller-supplied tenant ID cannot change access. The API requires a loopback client and host, rejects forwarded headers and non-local browser origins, and must run directly on loopback. Keep demo mode disabled for online deployments until authenticated company access and internal roles are implemented. There is no browser shared secret; `OPENAI_API_KEY` and `DATABASE_URL` remain backend-only.

Exact Windows PowerShell startup from the repository root (first stop any running backend with Ctrl+C):

```powershell
. .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
$env:DATABASE_URL = "sqlite:///./cargoai.db"
python -m alembic upgrade head
python -m database.seed
# Copy tenant_id printed by the seed command:
$env:CARGOAI_DEMO_TENANT_ID = "<seeded tenant UUID>"
$env:CARGOAI_LOCAL_DEMO = "1"
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000 --no-proxy-headers
```

In another PowerShell terminal:

```powershell
cd frontend
# frontend/.env.local: NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
npm install
npm run dev -- --hostname 127.0.0.1
```

Open `http://localhost:3000`. Paste a synthetic RFQ, extract, review the origin/destination, equipment, positive whole-number quantity, pricing date, currency, DG status and optional customer/incoterm, then calculate. Use pricing date **2026-10-15** for the October demo. Dates outside stored validity are rejected; expired rates never roll forward. Unknown DG status remains unknown and blocks calculation until confirmed. V1 rejects DG and equipment outside 20GP/40GP/40HC.

`GET /quote/lookups` returns shared canonical locations, supported equipment, and active customers scoped to the configured company. `GET /quote/lookups/resolve?kind=location&value=Shanghai` (or `kind=equipment`) reuses exact canonical/alias resolution with private aliases taking precedence over shared aliases. Ambiguity returns 409 and requires user selection; no fuzzy match is selected. Unknown extracted values remain visible.

Reviewed `POST /quote/spot` body (no tenant ID needed):

```json
{
  "origin_location_id": "<location UUID>",
  "destination_location_id": "<location UUID>",
  "equipment_type_id": "<equipment UUID>",
  "container_count": 3,
  "effective_date": "2026-10-15",
  "requested_currency": "USD",
  "dangerous_goods": false,
  "customer_id": null,
  "incoterm": "FOB"
}
```

Customer-facing charges allocate the engine's final sell total proportionally across its included charge lines, with the final line absorbing cent rounding. This is display allocation only; the engine arithmetic, charge bases, FX and rate/rule precedence are unchanged. Supplier amounts are never returned to this unauthenticated browser. The quote shows synthetic-demo labeling, selected rate reference and intersected sheet/rate validity. Editing any reviewed field clears the quote and invalidates pending responses; calculating never calls extraction again.

Offline verification (mocked extraction; no RFQs sent to OpenAI):

```powershell
. .\.venv\Scripts\Activate.ps1
# Tests mock extraction. If no backend key is configured, use a dummy key:
$env:OPENAI_API_KEY = "offline-test-placeholder"
python -m pytest tests -q
cd frontend
npm test -- --run
npx tsc --noEmit
npm run build
```

Backend tests use migrated temporary SQLite databases and seed rates. Tests cover the full mocked extraction → exact resolution → quote flow, quantity validation, unavailable/expired rates, missing FX, ambiguous references/rates, unsupported equipment/DG, company isolation and local-only access. Frontend tests cover review, explicit DG confirmation, calculation without re-extraction, errors and stale-response invalidation.

| Containers | Internal buy USD | Customer sell USD |
| --- | ---: | ---: |
| 1 | 1605.00 | 1797.60 |
| 2 | 3165.00 | 3544.80 |
| 3 | 4725.00 | 5292.00 |
| 10 | 15645.00 | 17522.40 |

## Commercial rates and commitments

Supplier `Rate` records distinguish short-term `SPOT` market rates from negotiated `CONTRACT` rates. Customer-facing `Quote` records also support `CUSTOMER_FIXED`: a forwarder's fixed sell-price commitment to a named tenant-owned customer, never a supplier buy rate. Supplier `valid_from`/`valid_to` and customer `quote_valid_from`/`quote_valid_until` remain independent; a customer commitment can outlast its original supplier rate without extending buy-rate eligibility. The legacy `Quote.valid_until` remains a compatibility alias.

Lanes are directional: China → Türkiye does not imply Türkiye → China. Stored supplier/market rates are the price source of truth; CargoAI does not derive market freight prices from geographic distance. Optional market, capacity, service-frequency, and disruption notes are stored but do not affect current pricing.

Industry-input cadence estimates are operational guidance only: ocean often weeks to about 3 months (special agreements about 6 months); international road weekly/monthly (special annual contracts); air daily/weekly. Rail is a future separate model. Explicit stored validity dates always win; there is no automatic cadence-based expiry.

A forwarder committing a 6- or 12-month customer price while buying at shorter market intervals takes market risk. Future analytics may use historical rates, disruptions, capacity, service frequency, trade imbalance, seasonality, and geopolitical events. Forecasting/risk pricing remains unimplemented and separate from deterministic pricing. See [commercial model details](docs/commercial-rate-model.md).

## Rate management

Internal/dev manual endpoints under `/admin/rates` manage tenant-scoped ocean FCL sheets, directional lanes, charges and versioned replacements. Lifecycle: **DRAFT → ACTIVE → EXPIRED → ARCHIVED**. Historical economics are never silently overwritten or deleted; quotes keep their exact original rate/charge references. Descriptive/status edits are audited, and economic changes create successor IDs with structured diffs. Overlap warnings and duplicate/ambiguity checks reuse existing pricing rules.

Every rate-management service request explicitly requires `tenant_id`. HTTP administration is blocked until authenticated internal access is implemented; service-level workflows and tests remain available. No frontend rate UI or file ingestion exists. Future Excel/CSV imports will use the same validation and service layer rather than bypassing business rules. See [API, versioning and import contract](docs/rate-management.md).
