// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
// Keys a careless backend might leak; the panel must never render any of these values.
const leaks = {
  carriers: [{ name: "Synthetic Ocean Line", email: "rates@carrier.example.com" }],
  carrier_name: "Synthetic Ocean Line", contact_email: "rates@carrier.example.com",
  reference_code: "CAI-RFQ-7Q2K9", buy_total: "987.65", price: "1234.56", rfq_body: "Dear carrier",
};
const leakedValues = ["Synthetic Ocean Line", "rates@carrier.example.com", "CAI-RFQ-7Q2K9", "987.65", "1234.56", "Dear carrier"];
const started = { quote_request_id: "qr-1", sourcing_status: "RFQ_DRAFTED", rfq_drafts_created: 3, already_existed: false, nothing_sent: true };
const status = { quote_request_id: "qr-1", sourcing_status: "AWAITING_REPLIES", rfq_drafts: 3, rfqs_sent: 2, replies_received: 1, rate_available: false };
const noRate = { detail: { status: "NO_RATE_FOUND", error: "No valid rate for shipment" } };

function response(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status }); }

let extraction: Record<string, unknown>;
let quoteHandler: () => Promise<Response>;
let startHandler: () => Promise<Response>;
let statusHandler: () => Promise<Response>;

beforeEach(() => {
  extraction = { ...extracted };
  quoteHandler = async () => response(noRate, 422);
  startHandler = async () => response({ ...started, ...leaks });
  statusHandler = async () => response({ ...status, ...leaks });
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input);
    if (url.pathname === "/parse/spot") return response({ result: extraction });
    if (url.pathname === "/quote/lookups") return response(lookups);
    if (url.pathname.endsWith("/resolve")) {
      return response({ id: url.searchParams.get("kind") === "equipment" ? "equip" : url.searchParams.get("value") === "Shanghai" ? "origin" : "dest" });
    }
    if (url.pathname === "/quote/spot" && init?.method === "POST") return quoteHandler();
    if (url.pathname === "/sourcing/requests" && init?.method === "POST") return startHandler();
    if (url.pathname === "/sourcing/requests/qr-1" && init?.method === "GET") return statusHandler();
    throw new Error(`Unexpected request ${input}`);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function extractOnly() {
  render(<Home />);
  fireEvent.change(screen.getByPlaceholderText(/Please quote Shanghai/), { target: { value: "Synthetic RFQ" } });
  fireEvent.click(screen.getByRole("button", { name: "Extract RFQ" }));
  await waitFor(() => expect((screen.getByRole("button", { name: "Calculate quote" }) as HTMLButtonElement).disabled).toBe(false));
}

async function calculate() {
  fireEvent.click(screen.getByRole("button", { name: "Calculate quote" }));
  await screen.findByRole("alert");
}

async function calculateWithoutRate() {
  await extractOnly();
  await calculate();
}

function bodyOf(path: string) {
  const call = vi.mocked(fetch).mock.calls.filter(([url]) => new URL(String(url)).pathname === path).at(-1);
  return JSON.parse(String(call?.[1]?.body)) as Record<string, unknown>;
}

function sourcingCalls() {
  return vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/sourcing/"));
}

function expectNoLeaks() {
  const text = document.body.innerHTML;
  for (const value of leakedValues) expect(text).not.toContain(value);
  expect(text).not.toContain("qr-1");
}

describe("Request carrier rates panel", () => {
  it("is offered only after NO_RATE_FOUND and does nothing until clicked", async () => {
    await calculateWithoutRate();
    expect(screen.getByRole("region", { name: "Carrier sourcing" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Request carrier rates" })).toBeTruthy();
    expect(sourcingCalls()).toHaveLength(0);
  });

  it("is absent for other pricing errors such as AMBIGUOUS_RATE", async () => {
    quoteHandler = async () => response({ detail: { status: "AMBIGUOUS_RATE", error: "Several rates match" } }, 409);
    await calculateWithoutRate();
    expect(screen.getByRole("alert").textContent).toContain("AMBIGUOUS_RATE");
    expect(screen.queryByRole("button", { name: "Request carrier rates" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Carrier sourcing" })).toBeNull();
  });

  it("posts the reviewed fields without a tenant id and shows only counts", async () => {
    await calculateWithoutRate();
    fireEvent.click(screen.getByRole("button", { name: "Request carrier rates" }));
    await screen.findByText("3 RFQ drafts prepared for internal review. Nothing has been sent.");
    const [, init] = sourcingCalls()[0];
    expect(init?.method).toBe("POST");
    const body = JSON.parse(String(init?.body));
    expect(body).toEqual({
      origin_location_id: "origin", destination_location_id: "dest", equipment_type_id: "equip", container_count: 2,
      effective_date: "2026-10-15", requested_currency: "USD", dangerous_goods: false, incoterm: "FOB",
    });
    expect(JSON.stringify(body)).not.toMatch(/tenant/i);
    expect(screen.queryByRole("button", { name: "Request carrier rates" })).toBeNull();
    expectNoLeaks();
  });

  it("shows the no-carrier message", async () => {
    startHandler = async () => response({ ...started, sourcing_status: "NO_CARRIER_AVAILABLE", rfq_drafts_created: 0 });
    await calculateWithoutRate();
    fireEvent.click(screen.getByRole("button", { name: "Request carrier rates" }));
    expect((await screen.findByText(/No suitable carrier configured/)).textContent).toContain("No suitable carrier configured");
    expect(screen.queryByRole("button", { name: "Refresh status" })).toBeNull();
  });

  it("shows the no-carrier message for a NO_CARRIER_AVAILABLE error code", async () => {
    startHandler = async () => response({ detail: { status: "NO_CARRIER_AVAILABLE", error: "No carriers" } }, 422);
    await calculateWithoutRate();
    fireEvent.click(screen.getByRole("button", { name: "Request carrier rates" }));
    await screen.findByText(/No suitable carrier configured/);
  });

  it("asks to recalculate on 409 RATE_AVAILABLE and recalculates", async () => {
    startHandler = async () => response({ detail: { status: "RATE_AVAILABLE", error: "A rate is available" } }, 409);
    await calculateWithoutRate();
    fireEvent.click(screen.getByRole("button", { name: "Request carrier rates" }));
    await screen.findByText("A rate is now available for this shipment. Recalculate the quote.");
    quoteHandler = async () => response(quote);
    fireEvent.click(screen.getByRole("button", { name: "Recalculate quote" }));
    await screen.findByRole("region", { name: "Calculated quote" });
    expect(screen.queryByRole("region", { name: "Carrier sourcing" })).toBeNull();
  });

  it("refreshes status, renders typed fields only, and prompts when a rate is available", async () => {
    await calculateWithoutRate();
    fireEvent.click(screen.getByRole("button", { name: "Request carrier rates" }));
    await screen.findByText(/3 RFQ drafts prepared/);
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    const details = await screen.findByLabelText("Sourcing status");
    expect(details.textContent).toContain("Awaiting carrier replies");
    expect(details.textContent).toContain("Replies received1");
    expect(details.textContent).not.toContain("Overdue");
    expectNoLeaks();
    statusHandler = async () => response({ ...status, sourcing_status: "RATE_RECEIVED", rate_available: true, rfqs_overdue: 0, ...leaks });
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    await screen.findByText("A rate is now available for this shipment. Recalculate the quote.");
    expect(screen.getByLabelText("Sourcing status").textContent).toContain("Overdue RFQs0");
    expect(screen.getByRole("button", { name: "Recalculate quote" })).toBeTruthy();
    expectNoLeaks();
    const [, init] = sourcingCalls()[1];
    expect(init?.method).toBe("GET");
  });

  it("shows status errors visibly", async () => {
    statusHandler = async () => response({ detail: { status: "NOT_FOUND", error: "Sourcing request not found" } }, 404);
    await calculateWithoutRate();
    fireEvent.click(screen.getByRole("button", { name: "Request carrier rates" }));
    await screen.findByText(/3 RFQ drafts prepared/);
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    await waitFor(() => expect(screen.getAllByRole("alert").some(node => node.textContent === "NOT_FOUND: Sourcing request not found")).toBe(true));
  });

  it("clears the panel on edit and ignores a stale sourcing response", async () => {
    let finish!: (value: Response) => void;
    startHandler = () => new Promise(resolve => { finish = resolve; });
    await calculateWithoutRate();
    fireEvent.click(screen.getByRole("button", { name: "Request carrier rates" }));
    await screen.findByRole("button", { name: "Requesting carrier rates..." });
    fireEvent.change(screen.getByLabelText("Container quantity"), { target: { value: "3" } });
    expect(screen.queryByRole("region", { name: "Carrier sourcing" })).toBeNull();
    await act(async () => { finish(response(started)); });
    expect(screen.queryByText(/RFQ drafts prepared/)).toBeNull();
    expect(screen.queryByRole("region", { name: "Carrier sourcing" })).toBeNull();
  });

  it("ignores a stale sourcing response after a new calculation", async () => {
    let finish!: (value: Response) => void;
    startHandler = () => new Promise(resolve => { finish = resolve; });
    await calculateWithoutRate();
    fireEvent.click(screen.getByRole("button", { name: "Request carrier rates" }));
    await screen.findByRole("button", { name: "Requesting carrier rates..." });
    fireEvent.click(screen.getByRole("button", { name: "Calculate quote" }));
    await screen.findByRole("button", { name: "Request carrier rates" });
    await act(async () => { finish(response(started)); });
    expect(screen.queryByText(/RFQ drafts prepared/)).toBeNull();
    expect(screen.getByRole("button", { name: "Request carrier rates" })).toBeTruthy();
  });
});

describe("Commodity and gross weight", () => {
  const weightInput = () => screen.getByLabelText("Gross weight (kg, optional)") as HTMLInputElement;
  const commodityInput = () => screen.getByLabelText("Commodity (optional)") as HTMLInputElement;

  it("prefills both fields from the parser output", async () => {
    extraction = { ...extracted, commodity: "  Machinery parts ", gross_weight_kg: 12500.5 };
    await extractOnly();
    expect(commodityInput().value).toBe("Machinery parts");
    expect(weightInput().value).toBe("12500.5");
    expect(screen.queryByText(/Gross weight must be/)).toBeNull();
  });

  it("shows null parser values as empty optional fields", async () => {
    extraction = { ...extracted, commodity: null, gross_weight_kg: null };
    await extractOnly();
    expect(commodityInput().value).toBe("");
    expect(weightInput().value).toBe("");
  });

  it("sends a trimmed commodity and the weight as a decimal string to sourcing only", async () => {
    extraction = { ...extracted, commodity: "Machinery parts", gross_weight_kg: 12500 };
    await extractOnly();
    fireEvent.change(commodityInput(), { target: { value: "  Textile machinery  " } });
    fireEvent.change(weightInput(), { target: { value: "12500.125" } });
    await calculate();
    const pricingBody = bodyOf("/quote/spot");
    expect(pricingBody).not.toHaveProperty("commodity");
    expect(pricingBody).not.toHaveProperty("gross_weight_kg");
    fireEvent.click(screen.getByRole("button", { name: "Request carrier rates" }));
    await screen.findByText(/3 RFQ drafts prepared/);
    const body = bodyOf("/sourcing/requests");
    expect(body.commodity).toBe("Textile machinery");
    expect(body.gross_weight_kg).toBe("12500.125");
    expect(typeof body.gross_weight_kg).toBe("string");
  });

  it("omits empty commodity and weight from the sourcing request", async () => {
    extraction = { ...extracted, commodity: "Machinery parts", gross_weight_kg: 12500 };
    await extractOnly();
    fireEvent.change(commodityInput(), { target: { value: "   " } });
    fireEvent.change(weightInput(), { target: { value: "" } });
    await calculate();
    fireEvent.click(screen.getByRole("button", { name: "Request carrier rates" }));
    await screen.findByText(/3 RFQ drafts prepared/);
    const body = bodyOf("/sourcing/requests");
    expect(body).not.toHaveProperty("commodity");
    expect(body).not.toHaveProperty("gross_weight_kg");
  });

  it.each([
    ["commodity", "Toys"],
    ["weight", "900"],
  ] as const)("editing %s clears the sourcing panel", async (field, value) => {
    await calculateWithoutRate();
    expect(screen.getByRole("region", { name: "Carrier sourcing" })).toBeTruthy();
    const input = field === "commodity" ? commodityInput() : weightInput();
    fireEvent.change(input, { target: { value } });
    expect(screen.queryByRole("region", { name: "Carrier sourcing" })).toBeNull();
    expect(input.value).toBe(value);
  });

  it.each(["0", "0.000", "-1", "abc", "1e3", "12.3456", "1,250", ".5"])("rejects weight %s and blocks the carrier request", async value => {
    await extractOnly();
    fireEvent.change(weightInput(), { target: { value } });
    expect(screen.getByText(/Gross weight must be a positive number in kg/)).toBeTruthy();
    expect(weightInput().getAttribute("aria-invalid")).toBe("true");
    // Weight does not affect pricing, so Calculate stays available.
    expect((screen.getByRole("button", { name: "Calculate quote" }) as HTMLButtonElement).disabled).toBe(false);
    await calculate();
    expect(bodyOf("/quote/spot")).not.toHaveProperty("gross_weight_kg");
    const button = screen.getByRole("button", { name: "Request carrier rates" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText("Correct the gross weight before requesting carrier rates.")).toBeTruthy();
    fireEvent.click(button);
    expect(sourcingCalls()).toHaveLength(0);
  });

  it("unblocks the request after the weight is corrected and recalculated", async () => {
    await extractOnly();
    fireEvent.change(weightInput(), { target: { value: "1e3" } });
    fireEvent.change(weightInput(), { target: { value: "1000" } });
    expect(screen.queryByText(/Gross weight must be/)).toBeNull();
    await calculate();
    const button = screen.getByRole("button", { name: "Request carrier rates" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    await screen.findByText(/3 RFQ drafts prepared/);
    expect(bodyOf("/sourcing/requests").gross_weight_kg).toBe("1000");
  });
});
