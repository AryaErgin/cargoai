// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "./page";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("CargoAI public alpha page", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.example");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("shows the alpha notice and privacy statement", () => {
    render(<Home />);

    expect(screen.getByRole("link", { name: "CargoAI home" })).toBeTruthy();
    expect(screen.getByText("AI-assisted freight request extraction — experimental alpha")).toBeTruthy();
    expect(screen.getByText("Always verify extracted information before operational use.")).toBeTruthy();
    expect(screen.getByText("Submitted text is processed for extraction and is not stored by this demo.")).toBeTruthy();
  });

  it("switches to the explicitly selected tender form", () => {
    render(<Home />);

    fireEvent.click(screen.getByRole("tab", { name: "Freight Tender" }));

    expect(screen.getByPlaceholderText("Paste a freight tender / lane entry...")).toBeTruthy();
    expect(screen.queryByPlaceholderText(/Please quote Shanghai/)).toBeNull();
  });

  it.each([
    ["Spot RFQ", "Please quote Shanghai", "Extract RFQ"],
    ["Freight Tender", "Paste a freight tender / lane entry...", "Extract Tender"],
  ])("updates the %s counter and extraction button from its input state", (tab, placeholder, buttonName) => {
    render(<Home />);
    if (tab === "Freight Tender") {
      fireEvent.click(screen.getByRole("tab", { name: tab }));
    }

    const textarea = screen.getByPlaceholderText(new RegExp(placeholder));
    const button = screen.getByRole("button", { name: buttonName }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText("0 / 20,000 characters")).toBeTruthy();

    fireEvent.change(textarea, { target: { value: "Hamburg to Oslo" } });
    expect(screen.getByText("15 / 20,000 characters")).toBeTruthy();
    expect(button.disabled).toBe(false);

    fireEvent.change(textarea, { target: { value: "" } });
    expect(screen.getByText("0 / 20,000 characters")).toBeTruthy();
    expect(button.disabled).toBe(true);
  });

  it("keeps Spot RFQ and Tender inputs independent when switching tabs", () => {
    render(<Home />);
    const spotTab = screen.getByRole("tab", { name: "Spot RFQ" });
    const tenderTab = screen.getByRole("tab", { name: "Freight Tender" });

    fireEvent.change(screen.getByPlaceholderText(/Please quote Shanghai/), {
      target: { value: "Spot shipment" },
    });
    fireEvent.click(tenderTab);
    expect((screen.getByPlaceholderText("Paste a freight tender / lane entry...") as HTMLTextAreaElement).value).toBe("");
    expect(screen.getByText("0 / 20,000 characters")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Extract Tender" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText("Paste a freight tender / lane entry..."), {
      target: { value: "Tender lane" },
    });
    fireEvent.click(spotTab);
    expect((screen.getByPlaceholderText(/Please quote Shanghai/) as HTMLTextAreaElement).value).toBe("Spot shipment");
    expect(screen.getByText("13 / 20,000 characters")).toBeTruthy();
    fireEvent.click(tenderTab);
    expect((screen.getByPlaceholderText("Paste a freight tender / lane entry...") as HTMLTextAreaElement).value).toBe("Tender lane");
    expect(screen.getByText("11 / 20,000 characters")).toBeTruthy();
  });

  it("posts tender text and renders missing fields clearly", async () => {
    const fetcher = vi.mocked(fetch);
    fetcher.mockResolvedValue(
      jsonResponse({
        type: "freight_tender",
        result: { pickup_location: "Hamburg", incoterm: null, equipment_quantity: 0 },
      }),
    );
    render(<Home />);
    fireEvent.click(screen.getByRole("tab", { name: "Freight Tender" }));
    fireEvent.change(screen.getByPlaceholderText("Paste a freight tender / lane entry..."), {
      target: { value: "Hamburg to Oslo, 2 x 40HC" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Extract Tender" }));

    expect(await screen.findByText("Hamburg")).toBeTruthy();
    expect(screen.getByText("0")).toBeTruthy();
    expect(screen.getAllByText("Not provided").length).toBeGreaterThan(0);
    expect(fetcher).toHaveBeenCalledWith(
      "http://api.example/parse/tender",
      expect.objectContaining({ body: JSON.stringify({ text: "Hamburg to Oslo, 2 x 40HC" }) }),
    );
  });

  it("renders every spot field and preserves boolean false as No", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        type: "spot_rfq",
        result: { origin: "Shanghai", dangerous_goods: false, unsupported_equipment: false },
      }),
    );
    render(<Home />);
    fireEvent.change(screen.getByPlaceholderText(/Please quote Shanghai/), {
      target: { value: "Shanghai to Ambarli" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Extract RFQ" }));
    await screen.findByText("Shanghai");

    for (const label of [
      "Origin",
      "Destination",
      "Container Type",
      "Raw Equipment",
      "Container Count",
      "Gross Weight",
      "Commodity",
      "Cargo Ready Date",
      "Required Arrival Date",
      "Incoterm",
      "Dangerous Goods",
      "HS Code",
      "Service Scope",
      "Unsupported Equipment",
    ]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getAllByText("No").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Not provided").length).toBeGreaterThan(0);
  });

  it("disables extraction for blank and over-limit input", () => {
    render(<Home />);
    const button = screen.getByRole("button", { name: "Extract RFQ" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/Please quote Shanghai/), {
      target: { value: "x".repeat(20_001) },
    });
    expect(button.disabled).toBe(true);
    expect(screen.getByText(`${(20_001).toLocaleString()} / 20,000 characters`)).toBeTruthy();
  });

  it("shows a loading state and prevents duplicate submits", async () => {
    let resolveRequest!: (response: Response) => void;
    vi.mocked(fetch).mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveRequest = resolve;
      }),
    );
    render(<Home />);
    fireEvent.change(screen.getByPlaceholderText(/Please quote Shanghai/), {
      target: { value: "Shanghai to Ambarli" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Extract RFQ" }));

    const loadingButton = screen.getByRole("button", { name: "Extracting..." }) as HTMLButtonElement;
    expect(loadingButton.disabled).toBe(true);
    resolveRequest(jsonResponse({ type: "spot_rfq", result: { origin: "Shanghai" } }));
    await waitFor(() => expect(screen.getByText("Shanghai")).toBeTruthy());
  });

  it("shows a useful message when the API cannot be reached", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("network down"));
    render(<Home />);
    fireEvent.change(screen.getByPlaceholderText(/Please quote Shanghai/), {
      target: { value: "Shanghai to Ambarli" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Extract RFQ" }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/could not reach the api/i);
  });

  it("clears the active input and extraction result", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ type: "spot_rfq", result: { origin: "Shanghai" } }),
    );
    render(<Home />);
    const textarea = screen.getByPlaceholderText(/Please quote Shanghai/) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Shanghai to Ambarli" } });
    fireEvent.click(screen.getByRole("button", { name: "Extract RFQ" }));
    await screen.findByText("Shanghai");

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(textarea.value).toBe("");
    expect(screen.queryByText("Spot RFQ details")).toBeNull();
  });
});
