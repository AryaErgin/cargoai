"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "../lib/pricing";
import {
  getSourcingStatus, startSourcing,
  type SourcingRequestBody, type SourcingStartResult, type SourcingStatus, type SourcingStatusResult,
} from "../lib/sourcing";

const STATUS_LABELS: Record<SourcingStatus, string> = {
  NONE: "Not started",
  NO_CARRIER_AVAILABLE: "No suitable carrier configured",
  RFQ_DRAFTED: "RFQ drafts prepared",
  AWAITING_REPLIES: "Awaiting carrier replies",
  RATE_RECEIVED: "Rate received",
  CANCELLED: "Cancelled",
};

const RATE_AVAILABLE_MESSAGE = "A rate is now available for this shipment. Recalculate the quote.";

function draftsMessage(count: number): string {
  return `${count} RFQ ${count === 1 ? "draft" : "drafts"} prepared for internal review. Nothing has been sent.`;
}

type Props = {
  /**
   * Reviewed shipment exactly as it was submitted to the failed calculation. Render with a `key` that
   * changes whenever the shipment changes so stale state and responses are discarded.
   */
  request: SourcingRequestBody;
  onRecalculate: () => void;
  /** When set, the request button is disabled and this reason is shown (e.g. invalid gross weight). */
  blockedReason?: string | null;
};

/**
 * Customer-safe "Request carrier rates" panel. Renders only typed counts and status values;
 * never carrier names, contact emails, prices or reference codes.
 */
export default function SourcingRequest({ request, onRecalculate, blockedReason = null }: Props) {
  const [started, setStarted] = useState<SourcingStartResult | null>(null);
  const [status, setStatus] = useState<SourcingStatusResult | null>(null);
  const [noCarrier, setNoCarrier] = useState(false);
  const [rateAvailable, setRateAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"starting" | "refreshing" | null>(null);
  const generation = useRef(0);

  // The parent keys this component by pricing revision, so a changed shipment remounts it with fresh
  // state. Unmounting invalidates any in-flight response.
  useEffect(() => () => { generation.current++; }, []);

  async function requestRates() {
    if (blockedReason) return;
    const current = ++generation.current;
    setError(null); setBusy("starting");
    try {
      const result = await startSourcing(request);
      if (generation.current !== current) return;
      setStarted(result);
      setNoCarrier(result.sourcing_status === "NO_CARRIER_AVAILABLE" || result.rfq_drafts_created === 0);
    } catch (failure) {
      if (generation.current !== current) return;
      if (failure instanceof ApiError && failure.code === "RATE_AVAILABLE") setRateAvailable(true);
      else if (failure instanceof ApiError && failure.code === "NO_CARRIER_AVAILABLE") setNoCarrier(true);
      else setError(failure instanceof Error ? failure.message : "Carrier sourcing failed.");
    } finally { if (generation.current === current) setBusy(null); }
  }

  async function refresh() {
    if (!started) return;
    const current = ++generation.current;
    setError(null); setBusy("refreshing");
    try {
      const result = await getSourcingStatus(started.quote_request_id);
      if (generation.current !== current) return;
      setStatus(result);
      if (result.rate_available) setRateAvailable(true);
    } catch (failure) {
      if (generation.current !== current) return;
      setError(failure instanceof Error ? failure.message : "Could not refresh sourcing status.");
    } finally { if (generation.current === current) setBusy(null); }
  }

  const canRefresh = started !== null && !noCarrier;

  return <section className="sourcing-panel" aria-label="Carrier sourcing" aria-busy={busy !== null}>
    <h4>Request carrier rates</h4>
    <p>No stored rate matches this shipment. CargoAI can prepare RFQ drafts for suitable carriers. Drafts are reviewed internally before anything is sent.</p>
    {!started && !noCarrier && !rateAvailable &&
      <button type="button" className="primary-button" onClick={requestRates} disabled={busy !== null || blockedReason !== null}
        aria-describedby={blockedReason ? "sourcing-blocked-reason" : undefined}>
        {busy === "starting" ? "Requesting carrier rates..." : "Request carrier rates"}
      </button>}
    {blockedReason && !started && <p id="sourcing-blocked-reason" className="input-hint">{blockedReason}</p>}
    {started && !noCarrier && <p role="status">
      {started.nothing_sent ? draftsMessage(started.rfq_drafts_created) : `${started.rfq_drafts_created} RFQ drafts prepared for internal review.`}
      {started.already_existed && " A sourcing request for this shipment already existed."}
    </p>}
    {noCarrier && <p role="status">No suitable carrier configured. Add rates manually or configure carriers for this lane.</p>}
    {status && <dl className="sourcing-status" aria-label="Sourcing status">
      <dt>Status</dt><dd>{status.sourcing_status ? STATUS_LABELS[status.sourcing_status] : "Not provided"}</dd>
      <dt>RFQ drafts</dt><dd>{status.rfq_drafts}</dd>
      <dt>RFQs sent</dt><dd>{status.rfqs_sent}</dd>
      <dt>Replies received</dt><dd>{status.replies_received}</dd>
      {status.rfqs_overdue !== null && <><dt>Overdue RFQs</dt><dd>{status.rfqs_overdue}</dd></>}
    </dl>}
    {canRefresh && !rateAvailable &&
      <button type="button" className="clear-button" onClick={refresh} disabled={busy !== null}>
        {busy === "refreshing" ? "Refreshing..." : "Refresh status"}
      </button>}
    {rateAvailable && <div className="sourcing-recalculate">
      <p role="status">{RATE_AVAILABLE_MESSAGE}</p>
      <button type="button" className="primary-button" onClick={onRecalculate}>Recalculate quote</button>
    </div>}
    {error && <p role="alert" className="api-error">{error}</p>}
  </section>;
}
