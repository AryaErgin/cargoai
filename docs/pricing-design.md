# Deterministic ocean-FCL pricing V1

Keep parsing separate. The engine accepts validated IDs/quantities/dates and explicit tenant/customer context, never an RFQ text blob. An API adapter resolves known location/equipment aliases without fuzzy matching. Only OCEAN_FCL and 20GP/40GP/40HC are supported.

Rate ranking: exact/exact, exact/group, group/exact, group/group; then priority descending; effective rate/sheet validity intersection width ascending (unbounded is widest); intersection start descending; sheet version descending; rate creation timestamp descending. Equal complete ranks fail. Equipment must match exactly. All eligible and rejected same-lane candidates have audit explanations. Historical candidates remain available for historical effective dates.

FX is tenant-scoped direct base→quote lookup with inclusive date validity. Same currency is explicitly identity conversion; there is no inverse or third-currency fallback. Missing or overlapping valid FX is a clear domain failure. Stored FX rows are immutable through ORM sessions.

Decimal precision is 38, rounding is ROUND_HALF_UP. Line totals round to two decimals; buy total sums those displayed line totals. Percentage bases are explicit: FREIGHT_SUBTOTAL or BUY_SUBTOTAL, both using applicable mandatory non-percentage charge subtotals before line rounding. Percentage charges never compound or include themselves. Bounds on a charge apply to its source-currency total before conversion. Unsupported mandatory bases/configurations fail; optional charges are reported without being priced.

Rules are selected independently for the primary markup slot (PERCENT_MARKUP competes with FIXED_MARKUP), minimum-margin slot, and discount slot. Specificity follows the user's eight tiers; priority breaks ties, remaining ties fail. Any origin/destination target is lane-specific. Minimum margin is an absolute monetary floor before discount. FIXED_MARKUP and MINIMUM_MARGIN require an explicit currency; percentage values are currency-independent. The user confirmed DISCOUNT is a percentage of sell after markup/minimum-margin. Margin percent means final margin / sell total × 100 (null when sell is zero).

The result snapshots selected rates, source amounts, FX values/IDs, rules and calculation bases. Optional persistence stores the full request/result audit JSON plus quote/quote-line relational references in a savepoint; the caller owns commit/rollback. The internal/dev API does not call OpenAI and is not connected to the frontend. Unknown/ambiguous references, invalid quantities, unsupported equipment and dangerous goods are rejected; V1 storage cannot express DG-qualified rates.

Migration 0002 adds exchange_rates, an explicit percentage_base on rate charges, and quote/line audit JSON. No prior migration, extraction schema, benchmark data, or parser is changed. Seed adds clearly synthetic FX examples for the existing demo tenant without changing its rates.
