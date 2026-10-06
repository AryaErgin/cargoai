# Commercial rate terms and forwarder commitments

Supplier costs and customer sell commitments are separate records and concepts.

- `Rate.commercial_type`: SPOT (short-term supplier/market buy rate) or CONTRACT (negotiated supplier buy rate). Its `valid_from`/`valid_to`, combined with the rate-sheet dates, determine buy-rate eligibility exactly as before.
- `Quote.commercial_type`: SPOT, CONTRACT, or CUSTOMER_FIXED. CUSTOMER_FIXED is a forwarder's customer price commitment, stored as customer-facing sell totals/lines and audit snapshot, never a supplier buy rate. It requires an explicit tenant-owned customer.
- `Quote.quote_valid_from`/`quote_valid_until` describe the customer commercial period. They can extend beyond supplier validity. The former `Quote.valid_until` remains an ORM alias to the renamed `quote_valid_until` column. No supplier dates are copied into customer dates automatically.

Existing rate/quote rows default to SPOT solely for backward compatibility; this does not retroactively classify their business origin. Existing expiry dates, amounts, rate IDs, and audit snapshots are preserved. New records should use explicit classifications supplied by the business. Supplier and customer terms do not add commercial-type ranking to the current engine. CUSTOMER_FIXED commitments are not read by the buy-rate selector and are not executed as a new sell-price override in V1.

Lanes are directional: origin → destination is an ordered pair, including group targets. China → Türkiye and Türkiye → China require independent stored rates. Neither repository lookup nor pricing reverses a lane.

Market freight prices are not calculated from geographic distance. Actual stored supplier/market rates remain the source of truth. Distance may later assist analytics, road-cost estimation, or forecasting; it must not replace rate data.

Optional `market_notes`, `capacity_notes`, `service_frequency_notes`, and `disruption_notes` on Rate are retained by version copying. They are nullable context for future analysis and are not used by current deterministic selection, charges, FX, or pricing rules.

## Operational cadence supplied by industry input

| Mode | Planning estimate, not an expiry rule |
|---|---|
| Ocean | Often weeks to about 3 months; special agreements may reach about 6 months |
| International road | Often weekly or monthly; special contracts may be annual |
| Air | Often daily to weekly |
| Rail | Future separate pricing model |

Actual explicit `valid_from`/`valid_to` always control. No cadence estimate creates an expiry, extends a rate, or permits using an expired supplier rate.

## Forwarder market risk and future analytics

Supplier buy-rate validity ≠ customer fixed-price commitment validity. A forwarder may promise a customer a 6- or 12-month fixed sell price while replacing shorter-lived supplier buy rates. The forwarder bears the resulting market risk. Keeping a commitment valid does not keep its original supplier cost eligible for new pricing.

A future, separate market-risk layer may analyze historical rates, route disruptions, capacity, service frequency, trade imbalance, seasonality, and geopolitical events. Forecasting and risk pricing are not implemented and must not silently change the deterministic engine's stored-rate arithmetic or selection policy.
