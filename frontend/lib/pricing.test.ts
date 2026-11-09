import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, errorFromResponse, pricingApi } from "./pricing";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try { await promise; } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error("expected rejection");
}

describe("pricingApi errors", () => {
  beforeEach(() => { vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.example/"); });
  afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

  it("extracts the domain code from detail.status and keeps the message text", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ detail: { status: "NO_RATE_FOUND", error: "No valid rate for shipment" } }, 422)));
    const error = await failure(pricingApi("/quote/spot", { a: 1 }));
    expect(error.status).toBe(422);
    expect(error.code).toBe("NO_RATE_FOUND");
    expect(error.message).toBe("NO_RATE_FOUND: No valid rate for shipment");
    expect(error).toBeInstanceOf(Error);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("http://api.example/quote/spot");
  });

  it("uses the default text when the error field is missing", () => {
    const error = errorFromResponse(409, { detail: { status: "RATE_AVAILABLE" } });
    expect(error.code).toBe("RATE_AVAILABLE");
    expect(error.message).toBe("RATE_AVAILABLE: Review the shipment fields.");
  });

  it("has no code for string and validation-list details", () => {
    expect(errorFromResponse(403, { detail: "Local demo access only" })).toMatchObject({ status: 403, code: null, message: "Local demo access only" });
    expect(errorFromResponse(422, { detail: [{ msg: "field required" }, { msg: "bad date" }] }))
      .toMatchObject({ code: null, message: "field required; bad date" });
    expect(errorFromResponse(500, null)).toMatchObject({ code: null, message: "Pricing failed: Review the shipment fields." });
  });

  it("reports an unreachable API with status 0", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    const error = await failure(pricingApi("/quote/lookups"));
    expect(error).toMatchObject({ status: 0, code: null, message: "Could not reach the pricing API." });
  });

  it("handles non-JSON error bodies", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Bad gateway", { status: 502 })));
    const error = await failure(pricingApi("/quote/lookups"));
    expect(error).toMatchObject({ status: 502, code: null });
  });
});
