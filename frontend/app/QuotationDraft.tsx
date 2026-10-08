"use client";

import { useState } from "react";
import type { CustomerQuote } from "../lib/pricing";

export default function QuotationDraft({ quote, incoterm }: { quote: CustomerQuote; incoterm: string }) {
  const [subject, setSubject] = useState(`Freight quotation: ${quote.shipment.origin} to ${quote.shipment.destination}`);
  const [body, setBody] = useState([
    ...(quote.demo_data ? ["SYNTHETIC DEMO — FOR LOCAL TESTING ONLY", ""] : []),
    "Dear customer,", "", "Thank you for your freight enquiry. Please find our quotation below:", "",
    `Route: ${quote.shipment.origin} to ${quote.shipment.destination}`,
    `Equipment: ${quote.shipment.container_count} x ${quote.shipment.equipment}`,
    `Pricing date: ${quote.shipment.effective_date}`,
    ...(incoterm ? [`Incoterm: ${incoterm}`] : []), "",
    ...quote.charges.map(charge => `${charge.description.replaceAll("_", " ")}: ${charge.sell_amount} ${quote.currency}`),
    `Total: ${quote.sell_total} ${quote.currency}`, "",
    "Please confirm availability, quotation validity, service scope and terms before sending.", "",
    "Kind regards,",
  ].join("\n"));
  const [message, setMessage] = useState("");

  async function copy() {
    try {
      await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`);
      setMessage("Quotation draft copied.");
    } catch {
      setMessage("Could not access the clipboard. Select and copy the draft manually.");
    }
  }

  return <section aria-label="Quotation email draft" className="result-card">
    <h3>Quotation email draft</h3>
    <p>Review and edit the message before sharing. Supplier rate dates are not customer quotation validity.</p>
    <label htmlFor="quotation-subject">Email subject</label>
    <input id="quotation-subject" value={subject} onChange={event => { setSubject(event.target.value); setMessage(""); }} />
    <label htmlFor="quotation-body">Email body</label>
    <textarea id="quotation-body" rows={16} value={body} onChange={event => { setBody(event.target.value); setMessage(""); }} />
    <button className="primary-button" type="button" onClick={copy}>Copy quotation draft</button>
    {message && <p role="status">{message}</p>}
  </section>;
}
