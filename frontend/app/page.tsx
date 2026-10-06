"use client";

import { useState, type FormEvent } from "react";
import ReviewShipment from "./ReviewShipment";

import { MAX_INPUT_LENGTH, requestExtraction, type ParserKind } from "../lib/parser";

type PanelState = {
  text: string;
  result: Record<string, unknown> | null;
  error: string | null;
  loading: boolean;
};

type ResultField = {
  key: string;
  label: string;
};

const RESULT_FIELDS: Record<ParserKind, ResultField[]> = {
  spot: [
    { key: "origin", label: "Origin" },
    { key: "destination", label: "Destination" },
    { key: "container_type", label: "Container Type" },
    { key: "raw_equipment", label: "Raw Equipment" },
    { key: "container_count", label: "Container Count" },
    { key: "gross_weight_kg", label: "Gross Weight" },
    { key: "commodity", label: "Commodity" },
    { key: "cargo_ready_date", label: "Cargo Ready Date" },
    { key: "required_arrival_date", label: "Required Arrival Date" },
    { key: "incoterm", label: "Incoterm" },
    { key: "dangerous_goods", label: "Dangerous Goods" },
    { key: "hs_code", label: "HS Code" },
    { key: "service_scope", label: "Service Scope" },
    { key: "unsupported_equipment", label: "Unsupported Equipment" },
  ],
  tender: [
    { key: "transport_mode", label: "Transport Mode" },
    { key: "pickup_location", label: "Pickup Location" },
    { key: "port_of_loading", label: "Port of Loading" },
    { key: "port_of_discharge", label: "Port of Discharge" },
    { key: "unloading_location", label: "Unloading Location" },
    { key: "equipment_type", label: "Equipment Type" },
    { key: "equipment_quantity", label: "Equipment Quantity" },
    { key: "incoterm", label: "Incoterm" },
  ],
};

const PLACEHOLDERS: Record<ParserKind, string> = {
  spot: "Please quote Shanghai to Ambarli.\n2x40HC automotive parts, 36,000 kg.\nFOB, non-DG.",
  tender: "Paste a freight tender / lane entry...",
};

const EMPTY_PANEL: PanelState = {
  text: "",
  result: null,
  error: null,
  loading: false,
};

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "Not provided";
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  return String(value);
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<ParserKind>("spot");
  const [panels, setPanels] = useState<Record<ParserKind, PanelState>>({
    spot: { ...EMPTY_PANEL },
    tender: { ...EMPTY_PANEL },
  });
  const panel = panels[activeTab];
  const text = panel.text;
  const loading = panel.loading;

  const updatePanel = (kind: ParserKind, changes: Partial<PanelState>) => {
    setPanels((current) => ({
      ...current,
      [kind]: { ...current[kind], ...changes },
    }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const kind = activeTab;
    const submittedText = panel.text;
    updatePanel(kind, { loading: true, error: null, result: null });

    try {
      const result = await requestExtraction(kind, submittedText);
      updatePanel(kind, { result, loading: false });
    } catch (error) {
      updatePanel(kind, {
        error: error instanceof Error ? error.message : "The extraction request failed.",
        loading: false,
      });
    }
  };

  const clearPanel = () => updatePanel(activeTab, { ...EMPTY_PANEL });
  const overLimit = text.length > MAX_INPUT_LENGTH;
  const extractLabel = activeTab === "spot" ? "Extract RFQ" : "Extract Tender";

  return (
    <main className="page-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="CargoAI home">
          <span className="brand-mark" aria-hidden="true">C</span>
          <span>CargoAI</span>
        </a>
        <span className="alpha-badge"><span className="status-dot" /> Experimental alpha</span>
      </header>

      <div className="content-column" id="top">
        <section className="intro-block" aria-labelledby="page-title">
          <p className="eyebrow">FREIGHT DATA WORKSPACE</p>
          <h1 id="page-title">AI-assisted freight request extraction — experimental alpha</h1>
          <p className="intro-copy">
            Turn a quote request or tender lane into structured fields. Choose the document type to get started.
          </p>
        </section>

        <aside className="verification-notice" role="note">
          <span className="notice-icon" aria-hidden="true">!</span>
          <p>Always verify extracted information before operational use.</p>
        </aside>

        <section className="workspace-card" aria-label="Freight extraction">
          <div className="workspace-heading">
            <div>
              <h2>Try an extraction</h2>
              <p>Select a format and paste the freight details below.</p>
            </div>
            <span className="field-count">14 fields <span aria-hidden="true">·</span> 8 fields</span>
          </div>

          <div className="tab-list" role="tablist" aria-label="Document type">
            <button
              id="spot-tab"
              className={`tab-button ${activeTab === "spot" ? "active" : ""}`}
              type="button"
              role="tab"
              aria-selected={activeTab === "spot"}
              aria-controls="parser-panel"
              onClick={() => setActiveTab("spot")}
            >
              <span className="tab-icon" aria-hidden="true">↗</span>
              Spot RFQ
            </button>
            <button
              id="tender-tab"
              className={`tab-button ${activeTab === "tender" ? "active" : ""}`}
              type="button"
              role="tab"
              aria-selected={activeTab === "tender"}
              aria-controls="parser-panel"
              onClick={() => setActiveTab("tender")}
            >
              <span className="tab-icon tender-icon" aria-hidden="true">▤</span>
              Freight Tender
            </button>
          </div>

          <section
            id="parser-panel"
            className="parser-panel"
            role="tabpanel"
            aria-labelledby={activeTab === "spot" ? "spot-tab" : "tender-tab"}
          >
            <form onSubmit={handleSubmit}>
              <div className="input-label-row">
                <label htmlFor="freight-text">
                  {activeTab === "spot" ? "Paste a freight quote request..." : "Paste a freight tender / lane entry..."}
                </label>
                <span className={overLimit ? "character-count over-limit" : "character-count"} aria-live="polite">
                  {text.length.toLocaleString()} / 20,000 characters
                </span>
              </div>
              <textarea
                id="freight-text"
                name="freight-text"
                value={text}
                onChange={(event) => updatePanel(activeTab, { text: event.target.value, error: null })}
                placeholder={PLACEHOLDERS[activeTab]}
                rows={7}
                aria-describedby="privacy-note"
              />
              {overLimit && <p className="input-hint error-text">Please shorten the text to 20,000 characters or fewer.</p>}

              <div className="form-actions">
                <button className="primary-button" type="submit" disabled={loading || !text.trim() || overLimit}>
                  {loading ? (
                    <><span className="spinner" aria-hidden="true" /> Extracting...</>
                  ) : (
                    <><span aria-hidden="true">✦</span> {extractLabel}</>
                  )}
                </button>
                <button className="clear-button" type="button" onClick={clearPanel} disabled={loading}>
                  Clear
                </button>
                <span className="privacy-lock" aria-hidden="true">◈</span>
              </div>
            </form>

            {panel.error && <p className="api-error" role="alert">{panel.error}</p>}

            {panel.result && (
              <section className="result-card" aria-labelledby="result-title" aria-live="polite">
                <div className="result-heading">
                  <div>
                    <p className="eyebrow">EXTRACTION COMPLETE</p>
                    <h3 id="result-title">{activeTab === "spot" ? "Spot RFQ details" : "Tender details"}</h3>
                  </div>
                  <span className="result-check" aria-hidden="true">✓</span>
                </div>
                <dl className="result-grid">
                  {RESULT_FIELDS[activeTab].map((field) => (
                    <div className="result-field" key={field.key}>
                      <dt>{field.label}</dt>
                      <dd>{displayValue(panel.result?.[field.key])}</dd>
                    </div>
                  ))}
                </dl>
                <p className="result-footnote">Review each field against the original request before use.</p>
              </section>
            )}
            {activeTab === "spot" && panel.result && <ReviewShipment extracted={panel.result} />}
          </section>
        </section>

        <p className="privacy-note" id="privacy-note">
          <span className="privacy-note-icon" aria-hidden="true">◈</span>
          Submitted text is processed for extraction and is not stored by this demo.
        </p>
        <footer className="page-footer">CargoAI <span>·</span> Experimental alpha</footer>
      </div>
    </main>
  );
}
