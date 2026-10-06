// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Home from "./page";

const extracted = { origin: "Shanghai", destination: "Ambarli", container_type: "40HQ", container_count: 2,
  cargo_ready_date: "2026-10-15", dangerous_goods: false, incoterm: "FOB" };
const lookups = { locations: [{ id: "origin", label: "Shanghai (CNSHA)" }, { id: "dest", label: "Ambarli (TRAMR)" }],
  equipment: [{ id: "equip", label: "40HC" }], customers: [], demo_data: true };
const quote = { status: "PRICED", currency: "USD", sell_total: "3544.80", shipment: {
  origin: "Shanghai", destination: "Ambarli", equipment: "40HC", container_count: 2, effective_date: "2026-10-15" },
  charges: [{ description: "OCEAN_FREIGHT", basis: "PER_CONTAINER", quantity: "2", sell_amount: "3544.80" }],
  selected_rate_id: "rate-id", rate_reference: "DEMO seed / rate 1", valid_from: "2026-10-01", valid_to: "2026-10-31",
  demo_data: true, charge_presentation: "Allocated sell charges" };
function response(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status }); }

let extraction = extracted as Record<string, unknown>;
let quoteHandler: () => Promise<Response>;
let ambiguous = false;

beforeEach(() => {
  extraction = { ...extracted }; ambiguous = false;
  quoteHandler = async () => response(quote);
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input);
    if (url.pathname === "/parse/spot") return response({ result: extraction });
    if (url.pathname === "/quote/lookups") return response(lookups);
    if (url.pathname.endsWith("/resolve")) {
      if (ambiguous && url.searchParams.get("value") === "Shanghai") return response({ detail: { status: "AMBIGUOUS_REFERENCE", error: "Select location" } }, 409);
      return response({ id: url.searchParams.get("kind") === "equipment" ? "equip" : url.searchParams.get("value") === "Shanghai" ? "origin" : "dest" });
    }
    if (url.pathname === "/quote/spot" && init?.method === "POST") return quoteHandler();
    throw new Error(`Unexpected request ${input}`);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function extract() {
  render(<Home />);
  fireEvent.change(screen.getByPlaceholderText(/Please quote Shanghai/), { target: { value: "Synthetic RFQ" } });
  fireEvent.click(screen.getByRole("button", { name: "Extract RFQ" }));
  await waitFor(() => expect((screen.getByRole("button", { name: "Calculate quote" }) as HTMLButtonElement).disabled).toBe(false));
}

describe("RFQ review and pricing", () => {
  it("prefills exact aliases, prices without extraction, and invalidates a quote on edit", async () => {
    await extract();
    expect((screen.getByLabelText("Equipment") as HTMLSelectElement).value).toBe("equip");
    fireEvent.click(screen.getByRole("button", { name: "Calculate quote" }));
    await screen.findByRole("region", { name: "Calculated quote" });
    expect(screen.getByText("Sell total: 3544.80 USD")).toBeTruthy();
    expect(screen.getByText("Synthetic demo rates — local testing only")).toBeTruthy();
    const calls = vi.mocked(fetch).mock.calls;
    expect(calls.filter(([url]) => String(url).includes("/parse/spot"))).toHaveLength(1);
    const pricingCall = calls.find(([url]) => String(url).endsWith("/quote/spot"));
    expect(JSON.parse(String(pricingCall?.[1]?.body))).toMatchObject({ origin_location_id: "origin", equipment_type_id: "equip", container_count: 2, dangerous_goods: false });
    fireEvent.change(screen.getByLabelText("Container quantity"), { target: { value: "3" } });
    expect(screen.queryByRole("region", { name: "Calculated quote" })).toBeNull();
  });

  it("discards an in-flight quote when reviewed inputs change", async () => {
    let finish!: (value: Response) => void;
    quoteHandler = () => new Promise(resolve => { finish = resolve; });
    await extract();
    fireEvent.click(screen.getByRole("button", { name: "Calculate quote" }));
    await screen.findByRole("button", { name: "Calculating..." });
    fireEvent.change(screen.getByLabelText("Pricing date"), { target: { value: "2026-11-01" } });
    await act(async () => { finish(response(quote)); });
    expect(screen.queryByRole("region", { name: "Calculated quote" })).toBeNull();
  });

  it("requires explicit confirmation of unknown dangerous goods", async () => {
    extraction.dangerous_goods = null;
    await extract();
    expect((screen.getByLabelText("Dangerous goods") as HTMLSelectElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Calculate quote" }));
    expect((await screen.findByRole("alert")).textContent).toContain("confirm dangerous-goods status");
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/quote/spot"))).toHaveLength(0);
  });

  it("keeps ambiguous locations unresolved for user selection", async () => {
    ambiguous = true;
    await extract();
    expect((screen.getByLabelText("Origin") as HTMLSelectElement).value).toBe("");
    expect(screen.getByText(/Shanghai: AMBIGUOUS_REFERENCE/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Origin"), { target: { value: "origin" } });
    fireEvent.click(screen.getByRole("button", { name: "Calculate quote" }));
    await screen.findByRole("region", { name: "Calculated quote" });
  });

  it("shows domain errors from pricing", async () => {
    quoteHandler = async () => response({ detail: { status: "NO_RATE_FOUND", error: "No valid rate for shipment" } }, 422);
    await extract();
    fireEvent.click(screen.getByRole("button", { name: "Calculate quote" }));
    expect((await screen.findByRole("alert")).textContent).toContain("NO_RATE_FOUND");
    expect(screen.queryByRole("region", { name: "Calculated quote" })).toBeNull();
  });
});
