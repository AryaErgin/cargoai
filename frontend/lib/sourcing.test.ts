import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./pricing";
import { buildSourcingRequest, getSourcingStatus, grossWeightError, parseStartResult, parseStatusResult, startSourcing } from "./sourcing";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const input = {
  origin_location_id: "origin", destination_location_id: "dest", equipment_type_id: "equip",
  container_count: 2, effective_date: "2026-10-15", requested_currency: "USD", dangerous_goods: false,
  incoterm: "FOB", customer_id: null,
};

describe("buildSourcingRequest", () => {
  it("copies only allowlisted fields and drops a tenant id or other extras", () => {
    const body = buildSourcingRequest({ ...input, tenant_id: "other-tenant", carrier: "x" } as typeof input);
    expect(body).toEqual({
      origin_location_id: "origin", destination_location_id: "dest", equipment_type_id: "equip",
      container_count: 2, effective_date: "2026-10-15", requested_currency: "USD", dangerous_goods: false, incoterm: "FOB",
    });
    expect(Object.keys(body)).not.toContain("tenant_id");
    expect(Object.keys(body)).not.toContain("customer_id");
  });

  it("refuses dangerous goods and invalid quantities", () => {
    expect(() => buildSourcingRequest({ ...input, dangerous_goods: true })).toThrow(/Dangerous-goods/);
    expect(() => buildSourcingRequest({ ...input, container_count: 0 })).toThrow(/positive whole number/);
    expect(() => buildSourcingRequest({ ...input, container_count: 1.5 })).toThrow(/positive whole number/);
  });
});

describe("response parsing", () => {
  it("keeps only typed start fields", () => {
    const parsed = parseStartResult({
      quote_request_id: "qr-1", sourcing_status: "RFQ_DRAFTED", rfq_drafts_created: 3, already_existed: false, nothing_sent: true,
      carriers: [{ name: "Carrier A", email: "rates@example.com" }], reference_code: "CAI-RFQ-ABC", buy_total: "1200.00",
    });
    expect(parsed).toEqual({ quote_request_id: "qr-1", sourcing_status: "RFQ_DRAFTED", rfq_drafts_created: 3, already_existed: false, nothing_sent: true });
  });

  it("maps unknown statuses to null and accepts an optional overdue count", () => {
    const base = { quote_request_id: "qr-1", sourcing_status: "SOMETHING_NEW", rfq_drafts: 2, rfqs_sent: 1, replies_received: 0, rate_available: false };
    expect(parseStatusResult(base)).toMatchObject({ sourcing_status: null, rfqs_overdue: null });
    expect(parseStatusResult({ ...base, rfqs_overdue: 1 })).toMatchObject({ rfqs_overdue: 1 });
  });

  it("rejects malformed responses", () => {
    expect(() => parseStartResult({ quote_request_id: "qr", rfq_drafts_created: "3", already_existed: false, nothing_sent: true })).toThrow(/unexpected/);
    expect(() => parseStatusResult({ quote_request_id: "qr", rfq_drafts: -1, rfqs_sent: 0, replies_received: 0, rate_available: false })).toThrow(/unexpected/);
    expect(() => parseStatusResult(null)).toThrow(/unexpected/);
  });
});

describe("sourcing API calls", () => {
  beforeEach(() => { vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.example"); });
  afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

  it("posts the reviewed fields to /sourcing/requests", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ quote_request_id: "qr-1", sourcing_status: "RFQ_DRAFTED", rfq_drafts_created: 2, already_existed: false, nothing_sent: true })));
    await startSourcing(buildSourcingRequest(input));
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("http://api.example/sourcing/requests");
    expect(init?.method).toBe("POST");
    const body = JSON.parse(String(init?.body));
    expect(body).toEqual(buildSourcingRequest(input));
    expect(JSON.stringify(body)).not.toMatch(/tenant/i);
  });

  it("surfaces RATE_AVAILABLE as a structured error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ detail: { status: "RATE_AVAILABLE", error: "A rate exists" } }, 409)));
    await expect(startSourcing(buildSourcingRequest(input))).rejects.toMatchObject({ status: 409, code: "RATE_AVAILABLE" });
    await expect(startSourcing(buildSourcingRequest(input))).rejects.toBeInstanceOf(ApiError);
  });

  it("fetches status with an encoded id via GET", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ quote_request_id: "a/b", sourcing_status: "AWAITING_REPLIES", rfq_drafts: 2, rfqs_sent: 2, replies_received: 1, rate_available: true })));
    const result = await getSourcingStatus("a/b");
    expect(result.rate_available).toBe(true);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("http://api.example/sourcing/requests/a%2Fb");
    expect(init?.method).toBe("GET");
  });
});

describe("gross weight", () => {
  it.each(["1", "12500", "12500.5", "12500.125", "0.001", " 42 "])("accepts %s", value => {
    expect(grossWeightError(value)).toBeNull();
  });

  it.each(["0", "0.0", "-1", "abc", "1e3", "1E3", "12.3456", "1,250", ".5", "5.", "+5", "Infinity", "1234567890123456"])("rejects %s", value => {
    expect(grossWeightError(value)).toMatch(/positive number in kg/);
  });

  it("treats empty values as not provided", () => {
    expect(grossWeightError("")).toBeNull();
    expect(grossWeightError("  ")).toBeNull();
    expect(grossWeightError(null)).toBeNull();
  });

  it("keeps commodity and weight as trimmed strings and refuses invalid weights", () => {
    const body = buildSourcingRequest({ ...input, commodity: "  Spare parts ", gross_weight_kg: " 12500.5 " });
    expect(body).toMatchObject({ commodity: "Spare parts", gross_weight_kg: "12500.5" });
    expect(() => buildSourcingRequest({ ...input, gross_weight_kg: "1e3" })).toThrow(/positive number in kg/);
  });
});
