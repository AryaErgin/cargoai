export type Option = { id: string; label: string };
export type Lookups = { locations: Option[]; equipment: Option[]; customers: Option[]; demo_data: boolean };
export type CustomerQuote = {
  status: string; currency: string; sell_total: string;
  shipment: { origin: string; destination: string; equipment: string; container_count: number; effective_date: string };
  charges: { description: string; basis: string; quantity: string; sell_amount: string }[];
  selected_rate_id: string; rate_reference: string; valid_from: string | null; valid_to: string | null;
  demo_data: boolean; charge_presentation: string;
};

/**
 * Error raised by API helpers. `status` is the HTTP status (0 when the API could not be reached),
 * `code` is the machine-readable domain code from `detail.status` (e.g. "NO_RATE_FOUND") or null.
 * `message` keeps the human-readable text shown to users.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    Object.setPrototypeOf(this, ApiError.prototype);
  }
}

export function apiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
}

/** Builds an ApiError from a non-OK response body, keeping the existing message format. */
export function errorFromResponse(status: number, data: unknown): ApiError {
  const detail = typeof data === "object" && data !== null ? (data as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string") return new ApiError(detail, status);
  if (Array.isArray(detail)) {
    return new ApiError(detail.map((item: { msg?: unknown }) => String(item?.msg ?? "")).join("; "), status);
  }
  const record = typeof detail === "object" && detail !== null ? detail as { status?: unknown; error?: unknown } : undefined;
  const code = typeof record?.status === "string" && record.status ? record.status : null;
  const text = typeof record?.error === "string" && record.error ? record.error : "Review the shipment fields.";
  return new ApiError(`${code || "Pricing failed"}: ${text}`, status, code);
}

export async function pricingApi<T>(path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      method: body ? "POST" : "GET", cache: "no-store",
      ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
    });
  } catch { throw new ApiError("Could not reach the pricing API.", 0); }
  let data: unknown;
  try { data = await response.json(); } catch {
    if (!response.ok) throw errorFromResponse(response.status, null);
    throw new ApiError("The pricing API returned an unreadable response.", response.status);
  }
  if (!response.ok) throw errorFromResponse(response.status, data);
  return data as T;
}
