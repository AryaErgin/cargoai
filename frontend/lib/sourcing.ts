import { pricingApi } from "./pricing";

/**
 * Customer-safe carrier sourcing API (plan 2026-11-09, Section 10.2).
 * Only counts and status are ever read from responses; any other key (carrier names, emails,
 * prices, reference codes, ...) is dropped by the parsers below and never reaches the UI.
 */

export const SOURCING_STATUSES = [
  "NONE", "NO_CARRIER_AVAILABLE", "RFQ_DRAFTED", "AWAITING_REPLIES", "RATE_RECEIVED", "CANCELLED",
] as const;
export type SourcingStatus = (typeof SOURCING_STATUSES)[number];

/** Reviewed shipment fields; mirrors the backend model (extra="forbid", no tenant id). */
export type SourcingRequestBody = {
  origin_location_id: string;
  destination_location_id: string;
  equipment_type_id: string;
  container_count: number;
  effective_date: string;
  requested_currency: string;
  dangerous_goods: false;
  incoterm?: string;
  customer_id?: string;
  commodity?: string;
  gross_weight_kg?: string;
};

export type SourcingStartResult = {
  quote_request_id: string;
  sourcing_status: SourcingStatus | null;
  rfq_drafts_created: number;
  already_existed: boolean;
  nothing_sent: boolean;
};

export type SourcingStatusResult = {
  quote_request_id: string;
  sourcing_status: SourcingStatus | null;
  rfq_drafts: number;
  rfqs_sent: number;
  replies_received: number;
  rate_available: boolean;
  rfqs_overdue: number | null;
};

type SourcingInput = {
  origin_location_id: string; destination_location_id: string; equipment_type_id: string;
  container_count: number; effective_date: string; requested_currency: string; dangerous_goods: boolean;
  incoterm?: string | null; customer_id?: string | null; commodity?: string | null; gross_weight_kg?: string | null;
};

const unexpected = () => new Error("The sourcing API returned an unexpected response.");

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function count(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw unexpected();
  return value;
}

function flag(value: unknown): boolean {
  if (typeof value !== "boolean") throw unexpected();
  return value;
}

function requestId(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) throw unexpected();
  return value;
}

function status(value: unknown): SourcingStatus | null {
  return typeof value === "string" && (SOURCING_STATUSES as readonly string[]).includes(value) ? value as SourcingStatus : null;
}

// Mirrors the backend rule in sourcing/models.py (_WEIGHT): up to 15 integer digits, up to 3 decimals.
const GROSS_WEIGHT_PATTERN = /^\d{1,15}(\.\d{1,3})?$/;

/**
 * Validates an optional gross weight in kg typed by the user. Returns an error message, or null when
 * the value is empty or valid. Valid: plain decimal, greater than zero, at most 3 decimals, dot as the
 * decimal separator. Rejected: zero, negatives, exponent notation, separators, other text.
 */
export function grossWeightError(value: string | null | undefined): string | null {
  const text = (value ?? "").trim();
  if (!text) return null;
  if (!GROSS_WEIGHT_PATTERN.test(text) || !/[1-9]/.test(text)) {
    return "Gross weight must be a positive number in kg with at most 3 decimals (for example 12500 or 12500.5).";
  }
  return null;
}

/**
 * Builds the POST body from an explicit allowlist. Unknown keys (e.g. a tenant id) are never copied.
 * Empty optional values are omitted. Throws if the shipment is not sourceable (DG must be false).
 */
export function buildSourcingRequest(input: SourcingInput): SourcingRequestBody {
  if (input.dangerous_goods !== false) throw new Error("Dangerous-goods shipments cannot be sourced.");
  if (!Number.isSafeInteger(input.container_count) || input.container_count <= 0) {
    throw new Error("Container quantity must be a positive whole number.");
  }
  const weightError = grossWeightError(input.gross_weight_kg);
  if (weightError) throw new Error(weightError);
  const body: SourcingRequestBody = {
    origin_location_id: input.origin_location_id,
    destination_location_id: input.destination_location_id,
    equipment_type_id: input.equipment_type_id,
    container_count: input.container_count,
    effective_date: input.effective_date,
    requested_currency: input.requested_currency,
    dangerous_goods: false,
  };
  for (const key of ["incoterm", "customer_id", "commodity", "gross_weight_kg"] as const) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) body[key] = value.trim();
  }
  return body;
}

export function parseStartResult(data: unknown): SourcingStartResult {
  if (!isRecord(data)) throw unexpected();
  return {
    quote_request_id: requestId(data.quote_request_id),
    sourcing_status: status(data.sourcing_status),
    rfq_drafts_created: count(data.rfq_drafts_created),
    already_existed: flag(data.already_existed),
    nothing_sent: flag(data.nothing_sent),
  };
}

export function parseStatusResult(data: unknown): SourcingStatusResult {
  if (!isRecord(data)) throw unexpected();
  return {
    quote_request_id: requestId(data.quote_request_id),
    sourcing_status: status(data.sourcing_status),
    rfq_drafts: count(data.rfq_drafts),
    rfqs_sent: count(data.rfqs_sent),
    replies_received: count(data.replies_received),
    rate_available: flag(data.rate_available),
    rfqs_overdue: data.rfqs_overdue === undefined || data.rfqs_overdue === null ? null : count(data.rfqs_overdue),
  };
}

export async function startSourcing(body: SourcingRequestBody): Promise<SourcingStartResult> {
  return parseStartResult(await pricingApi<unknown>("/sourcing/requests", buildSourcingRequest(body)));
}

export async function getSourcingStatus(quoteRequestId: string): Promise<SourcingStatusResult> {
  if (!quoteRequestId.trim()) throw new Error("Missing sourcing request id.");
  return parseStatusResult(await pricingApi<unknown>(`/sourcing/requests/${encodeURIComponent(quoteRequestId)}`));
}
