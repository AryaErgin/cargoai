# Manual Rate Management V1

Internal/dev API only: no authentication yet. Explicit `tenant_id` is required on every request and every service operation. Do not publish these endpoints without authentication/authorization. V1 supports manual supplier `OCEAN_FCL` rates for `20GP`, `40GP`, `40HC`; `CUSTOMER_FIXED` remains a customer quote commitment, not supplier economics.

## Lifecycle and storage

`DRAFT → ACTIVE → EXPIRED → ARCHIVED`. Drafts are not priceable. Activation requires a mandatory charge; dates still control applicability. Explicit expiry/archive toggles pricing eligibility without deletion. Archival cannot be undone in place; create a successor. Nothing expires automatically based on market-cadence estimates.

Sheets are created ACTIVE and with root version 1. New rates default to DRAFT. Assemble charges, then activate using `/update`. Supplying initial charges allows atomic ACTIVE creation. Rates, suppliers, groups, events and version links are tenant scoped. Locations/equipment/charge types are shared reference data. Origin and destination are directional and are never reversed.

## Endpoints

All POST bodies include `tenant_id`; GET requests require it as a query parameter.

| Method | Path | Operation |
| --- | --- | --- |
| POST | `/admin/rates/sheets` | Create MANUAL rate sheet |
| POST | `/admin/rates` | Create rate, optionally with `charges` |
| POST | `/admin/rates/{id}/charges` | Add charge; versions non-drafts |
| GET | `/admin/rates/{id}` | Read supplier/lane/groups/equipment/charges/source/version links |
| GET | `/admin/rates` | Filter and paginate scoped rates |
| POST | `/admin/rates/{id}/update` | Apply descriptive/status edits or economic successor |
| POST | `/admin/rates/{id}/version` | Copy rate and charges with explicit patches |
| POST | `/admin/rates/{id}/deactivate` | Set EXPIRED or ARCHIVED (default) |

List filters: supplier UUID, origin/destination location or group UUID, equipment UUID, mode, status, `valid_on`, commercial type. Location filters include tenant group membership. Default ordering: priority, sheet version, newest creation, stable UUID. Limit defaults to 50 (1–1000); offset defaults to 0. `valid_on` filters date applicability, not lifecycle status; supply `status=ACTIVE` for active records. Responses include total count.

## Versioning and diffs

Every rate-field change except the five descriptive note fields and lifecycle status creates new rate, sheet and charge IDs, including supplier, equipment, lane targets, validity, priority, service name/code, commercial type and source reference. Changes to any charge economics or applicability create a version. Direct ORM economic updates/bulk updates/deletions remain forbidden. Drafts may append charges before activation; existing charge rows are still immutable. Adding a charge to an ACTIVE/EXPIRED/ARCHIVED rate creates a successor. Optional charges, bounds and equipment/date restrictions are preserved.

Each version is a **single-rate successor sheet snapshot**. Unrelated source-sheet lanes are not cloned or changed. A sheet lineage allocates increasing versions; an exact old/new rate link is retained in append-only `rate_events`. Earlier rate versions remain ACTIVE for their valid historical dates unless explicitly deactivated. Overlapping versions use the unchanged pricing precedence. Editing an already superseded rate economically returns `STALE_VERSION`.

Descriptive notes (`notes`, `market_notes`, `capacity_notes`, `service_frequency_notes`, `disruption_notes`) and status may change in place only through the audited service path. Successful commands record changes; they do not overwrite quote snapshots or source economics. Callers own the outer transaction; each command has a rollback savepoint. PostgreSQL locks the tenant row to serialize management writes. Privileged SQL/legacy repository callers are outside this boundary and must not be used by importers.

Example November replacement (monetary values are decimal strings):

```json
{
  "tenant_id": "<tenant UUID>",
  "changes": {"valid_from": "2026-11-01", "valid_to": "2026-11-30"},
  "charge_changes": {"<old freight charge UUID>": {"amount": "1380"}}
}
```

`POST /admin/rates/<October rate UUID>/version` returns `old_rate_id`, `new_rate_id`, `changes` (field/old/new), readable rate details and warnings. Charges are referenced by their old UUIDs, so repeated charge types are unambiguous. Omitted patch fields are retained; explicit nulls are validated. Cloned explicit charge dates must remain inside the successor validity; adjust them explicitly where necessary. NULL charge dates inherit the rate window.

## Validation, overlap and duplicates

Exactly one location or group per lane side is mandatory. Owned references must belong to the tenant. Supplier and commercial type must match the sheet. Validity bounds must be ordered and lie within the parent. Charge amounts/bounds are finite nonnegative Decimals; currencies are three-letter codes. Allowed bases: PER_CONTAINER, PER_SHIPMENT, FLAT, PERCENTAGE. Percentage values are 0–100 and must explicitly specify FREIGHT_SUBTOTAL or BUY_SUBTOTAL, using existing pricing semantics.

Overlapping directional lanes (including intersecting groups) are checked with the existing pricing rank: specificity, priority, narrower window, later start, sheet version, newest creation. Identical complete ranks are rejected as AMBIGUOUS_RATE; no UUID guess. Same-supplier/specificity overlaps produce EXACT_OVERLAP, PARTIAL_DATE_OVERLAP and, where applicable, LOWER_PRIORITY_OVERLAP warnings. Resolvable overlaps are retained rather than indiscriminately rejected.

Identical tenant/supplier/lane/equipment/effective validity/commercial type and charge economics are rejected as DUPLICATE_RATE, regardless of descriptive notes, lifecycle state or higher priority. Numeric trailing zeros do not disguise duplicates. Empty identical draft rates also conflict. Duplicate charges and unchanged successors are rejected. Errors use 404 for inaccessible resources, 409 for conflicts, 422 for invalid inputs; infrastructure failures use a generic 503 without stack traces.

Manual entries record MANUAL on the sheet and an optional `source_reference`, e.g. `Entered from carrier email 2026-10-06`; no raw email is needed. Details return charge count/currencies/bases, not a summed buy/sell price across mixed bases or currencies. Existing persisted quotes retain old rate/charge IDs and calculated audit snapshots.

## Future imports

`parsed spreadsheet row → strict request model → shared validation → duplicate/overlap check → rate-management service → database`.

Excel/CSV importers must call these same services; they must not insert rates through raw repositories or SQL. Next: define a staging-row/import review model and column-mapping adapter, then submit approved rows through this service. File uploads/parsing are not implemented in V1.
