import { beforeEach, describe, expect, it, vi } from "vitest";

import { requestExtraction } from "./parser";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("requestExtraction", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.example/");
  });

  it("rejects whitespace without making a request", async () => {
    const fetcher = vi.fn<typeof fetch>();

    await expect(requestExtraction("spot", "  \n", fetcher)).rejects.toThrow(/enter text/i);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("accepts 20,000 characters and returns the result object", async () => {
    const text = "x".repeat(20_000);
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ type: "spot_rfq", result: { origin: "Shanghai" } }));

    await expect(requestExtraction("spot", text, fetcher)).resolves.toEqual({
      origin: "Shanghai",
    });
    expect(fetcher).toHaveBeenCalledWith(
      "http://api.example/parse/spot",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ text }),
      }),
    );
  });

  it.each(["spot", "tender"] as const)("uses the %s endpoint", async (kind) => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ type: "result", result: { ok: true } }),
    );

    await requestExtraction(kind, "RFQ", fetcher);

    expect(fetcher.mock.calls[0][0]).toBe(`http://api.example/parse/${kind}`);
  });

  it("rejects 20,001 characters before fetching", async () => {
    const fetcher = vi.fn<typeof fetch>();

    await expect(requestExtraction("spot", "x".repeat(20_001), fetcher)).rejects.toThrow(
      /20,000/,
    );
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("uses backend detail for unsuccessful responses", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ detail: "Parser unavailable" }, 502),
    );

    await expect(requestExtraction("tender", "RFQ", fetcher)).rejects.toThrow(
      "Parser unavailable",
    );
  });

  it("reports when the API cannot be reached", async () => {
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("network down"));

    await expect(requestExtraction("spot", "RFQ", fetcher)).rejects.toThrow(/could not reach/i);
  });
});
