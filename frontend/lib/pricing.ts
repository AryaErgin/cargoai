export type Option = { id: string; label: string };
export type Lookups = { locations: Option[]; equipment: Option[]; customers: Option[]; demo_data: boolean };
export type CustomerQuote = {
  status: string; currency: string; sell_total: string;
  shipment: { origin: string; destination: string; equipment: string; container_count: number; effective_date: string };
  charges: { description: string; basis: string; quantity: string; sell_amount: string }[];
  selected_rate_id: string; rate_reference: string; valid_from: string | null; valid_to: string | null;
  demo_data: boolean; charge_presentation: string;
};

export async function pricingApi<T>(path: string, body?: unknown): Promise<T> {
  const base = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method: body ? "POST" : "GET", cache: "no-store",
      ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
    });
  } catch { throw new Error("Could not reach the pricing API."); }
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail :
      Array.isArray(detail) ? detail.map((item: { msg: string }) => item.msg).join("; ") :
      `${detail?.status || "Pricing failed"}: ${detail?.error || "Review the shipment fields."}`);
  }
  return data as T;
}
