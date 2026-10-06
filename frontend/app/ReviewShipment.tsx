"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { pricingApi, type Lookups, type CustomerQuote, type Option } from "../lib/pricing";

type Shipment = {
  origin_location_id: string; destination_location_id: string; equipment_type_id: string;
  container_count: string; effective_date: string; requested_currency: string;
  dangerous_goods: string; customer_id: string; incoterm: string;
};

export default function ReviewShipment({ extracted }: { extracted: Record<string, unknown> }) {
  const [shipment, setShipment] = useState<Shipment>({
    origin_location_id: "", destination_location_id: "", equipment_type_id: "",
    container_count: extracted.container_count == null ? "" : String(extracted.container_count),
    effective_date: typeof extracted.cargo_ready_date === "string" ? extracted.cargo_ready_date : "",
    requested_currency: "USD", dangerous_goods: typeof extracted.dangerous_goods === "boolean" ? String(extracted.dangerous_goods) : "",
    customer_id: "", incoterm: typeof extracted.incoterm === "string" ? extracted.incoterm : "",
  });
  const [lookups, setLookups] = useState<Lookups | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [quote, setQuote] = useState<CustomerQuote | null>(null);
  const [loading, setLoading] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const revision = useRef(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    let cancelled = false;
    const initialRevision = revision.current;
    async function initialize() {
      try {
        const choices = await pricingApi<Lookups>("/quote/lookups");
        if (cancelled) return;
        setLookups(choices);
        const fields = [
          ["origin_location_id", "location", extracted.origin, choices.locations],
          ["destination_location_id", "location", extracted.destination, choices.locations],
          ["equipment_type_id", "equipment", extracted.unsupported_equipment ? null : extracted.container_type, choices.equipment],
        ] as const;
        const messages: string[] = [];
        const matches = await Promise.all(fields.map(async ([field, kind, value, options]) => {
          if (typeof value !== "string" || !value.trim()) {
            messages.push(`${field.replaceAll("_", " ")}: not resolved; select a value.`);
            return [field, ""];
          }
          try {
            const match = await pricingApi<{ id: string }>(`/quote/lookups/resolve?kind=${kind}&value=${encodeURIComponent(value)}`);
            if (!options.some(option => option.id === match.id)) throw new Error("Unsupported equipment");
            return [field, match.id];
          } catch (failure) {
            messages.push(`${value}: ${failure instanceof Error ? failure.message : "unresolved"} Select explicitly.`);
            return [field, ""];
          }
        }));
        if (cancelled) return;
        setWarnings(messages);
        if (revision.current === initialRevision) setShipment(current => ({ ...current, ...Object.fromEntries(matches) }));
      } catch (failure) {
        if (!cancelled) setError(failure instanceof Error ? failure.message : "Lookups unavailable");
      } finally { if (!cancelled) setInitializing(false); }
    }
    void initialize();
    return () => { cancelled = true; alive.current = false; revision.current++; };
  }, [extracted]);

  function edit(field: keyof Shipment, value: string) {
    revision.current++;
    setShipment(current => ({ ...current, [field]: value }));
    setQuote(null); setError(null); setLoading(false);
  }

  async function calculate(event: FormEvent) {
    event.preventDefault();
    setQuote(null); setError(null);
    if (!shipment.origin_location_id || !shipment.destination_location_id || !shipment.equipment_type_id ||
        !shipment.effective_date || !/^[A-Z]{3}$/.test(shipment.requested_currency) || shipment.dangerous_goods === "" ||
        !/^[1-9]\d*$/.test(shipment.container_count) || !Number.isSafeInteger(Number(shipment.container_count))) {
      setError("Select locations and supported equipment, enter a positive whole-number quantity, pricing date, three-letter currency, and confirm dangerous-goods status.");
      return;
    }
    const submittedRevision = ++revision.current;
    setLoading(true);
    try {
      const result = await pricingApi<CustomerQuote>("/quote/spot", {
        ...shipment, container_count: Number(shipment.container_count), dangerous_goods: shipment.dangerous_goods === "true",
        customer_id: shipment.customer_id || null, incoterm: shipment.incoterm || null,
      });
      if (alive.current && revision.current === submittedRevision) setQuote(result);
    } catch (failure) {
      if (alive.current && revision.current === submittedRevision) setError(failure instanceof Error ? failure.message : "Pricing failed");
    } finally { if (alive.current && revision.current === submittedRevision) setLoading(false); }
  }

  function selector(label: string, field: keyof Shipment, options: Option[], optional = false) {
    return <label>{label}<select value={shipment[field]} onChange={event => edit(field, event.target.value)}>
      <option value="">{optional ? "Default customer pricing" : "Unresolved — select"}</option>
      {options.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
    </select></label>;
  }

  return <section className="result-card" aria-label="Review shipment">
    <h3>Review shipment</h3>
    <p>Confirm extracted values before calculating. Unknown dangerous-goods status requires an explicit choice.</p>
    <p>Extracted route: {String(extracted.origin ?? "Not provided")} → {String(extracted.destination ?? "Not provided")}; equipment: {String(extracted.raw_equipment ?? extracted.container_type ?? "Not provided")}</p>
    {warnings.map(message => <p key={message} className="input-hint">{message}</p>)}
    {initializing && <p role="status">Resolving shipment references...</p>}
    <form onSubmit={calculate}>
      <fieldset disabled={initializing || !lookups} className="review-grid">
        {selector("Origin", "origin_location_id", lookups?.locations || [])}
        {selector("Destination", "destination_location_id", lookups?.locations || [])}
        {selector("Equipment", "equipment_type_id", lookups?.equipment || [])}
        <label>Container quantity<input type="number" min="1" step="1" value={shipment.container_count} onChange={event => edit("container_count", event.target.value)} /></label>
        <label>Pricing date<input type="date" value={shipment.effective_date} onChange={event => edit("effective_date", event.target.value)} /></label>
        <label>Quote currency<input maxLength={3} value={shipment.requested_currency} onChange={event => edit("requested_currency", event.target.value.toUpperCase())} /></label>
        <label>Dangerous goods<select value={shipment.dangerous_goods} onChange={event => edit("dangerous_goods", event.target.value)}>
          <option value="">Unknown — confirm</option><option value="false">No</option><option value="true">Yes — unsupported</option>
        </select></label>
        {selector("Customer", "customer_id", lookups?.customers || [], true)}
        <label>Incoterm<input value={shipment.incoterm} onChange={event => edit("incoterm", event.target.value)} /></label>
      </fieldset>
      <button className="primary-button" type="submit" disabled={initializing || !lookups || loading}>{loading ? "Calculating..." : "Calculate quote"}</button>
    </form>
    {error && <p role="alert" className="api-error">{error}</p>}
    {quote && <section aria-label="Calculated quote" aria-live="polite">
      <h3>Shipment quote</h3>
      {quote.demo_data && <p className="verification-notice">Synthetic demo rates — local testing only</p>}
      <p>{quote.shipment.origin} → {quote.shipment.destination} · {quote.shipment.container_count} × {quote.shipment.equipment} · Pricing date {quote.shipment.effective_date}</p>
      <p>Dangerous goods: {shipment.dangerous_goods === "true" ? "Yes" : "No"} · Incoterm: {shipment.incoterm || "Not provided"} · Customer: {lookups?.customers.find(row => row.id === shipment.customer_id)?.label || "Default pricing"}</p>
      <table><thead><tr><th>Charge</th><th>Basis</th><th>Quantity</th><th>Sell ({quote.currency})</th></tr></thead>
        <tbody>{quote.charges.map((charge, index) => <tr key={index}><td>{charge.description.replaceAll("_", " ")}</td><td>{charge.basis}</td><td>{charge.quantity}</td><td>{charge.sell_amount}</td></tr>)}</tbody>
      </table>
      <p><strong>Sell total: {quote.sell_total} {quote.currency}</strong></p>
      <p>{quote.charge_presentation}</p>
      <p>Rate: {quote.rate_reference} ({quote.selected_rate_id}) · Valid {quote.valid_from || "open"} to {quote.valid_to || "open"}</p>
    </section>}
  </section>;
}
