# CargoAI Public Alpha Frontend Design

## Goal

Add a minimal public-alpha web interface for trying the existing CargoAI Spot RFQ and Freight Tender extraction endpoints. The frontend must make the document type an explicit user choice and display parser output clearly while reminding users to verify it.

## Approved Architecture

- Create a standalone Next.js App Router application under `frontend/` using TypeScript and plain CSS.
- Implement one client-side page with explicit Spot RFQ and Freight Tender tabs. Do not add type auto-detection.
- Send browser `fetch` requests directly to the FastAPI backend. Do not add a Next.js proxy.
- Read the backend base URL from `NEXT_PUBLIC_API_BASE_URL`, with local development configured to `http://127.0.0.1:8000`.
- Configure FastAPI CORS for one environment-configured frontend origin, `CARGOAI_FRONTEND_ORIGIN`, defaulting to `http://localhost:3000`. Permit only the methods and headers needed by this interface; do not use wildcard origins or credentials.

## Page and Interaction

The page header displays `CargoAI`, the subtitle `AI-assisted freight request extraction — experimental alpha`, and the visible warning `Always verify extracted information before operational use.` A privacy note reads `Submitted text is processed for extraction and is not stored by this demo.`

Provide tabs labeled `Spot RFQ` and `Freight Tender`. Each tab has a labeled textarea, a 20,000-character counter and limit, an Extract button, and a clear/reset button. Disable extraction for blank/whitespace-only text and while the request is running. While running, show a clear loading state. Requests above 20,000 characters are rejected in the interface, and the backend remains authoritative for its existing 400 validation.

Spot placeholder text:

```text
Please quote Shanghai to Ambarli.
2x40HC automotive parts, 36,000 kg.
FOB, non-DG.
```

Spot submits `POST {API_BASE}/parse/spot` with `{"text":"..."}` and labels results in this order: Origin, Destination, Container Type, Raw Equipment, Container Count, Gross Weight, Commodity, Cargo Ready Date, Required Arrival Date, Incoterm, Dangerous Goods, HS Code, Service Scope, Unsupported Equipment.

Tender submits `POST {API_BASE}/parse/tender` with `{"text":"..."}` and labels results in this order: Transport Mode, Pickup Location, Port of Loading, Port of Discharge, Unloading Location, Equipment Type, Equipment Quantity, Incoterm.

Render `null` and absent values as `Not provided`. Preserve meaningful non-string values such as `false` and `0`. Render API errors in a visible, accessible error area, using the backend's safe detail when available and a plain connection message when the API cannot be reached. Clear/reset removes the current input, result, and error.

## Privacy and Scope

Do not store submitted text in a database, browser storage, cookies, or analytics. Do not add analytics, request-body logging, authentication, pricing, booking, or deployment configuration. The frontend only submits text to the configured FastAPI origin. Never place `OPENAI_API_KEY` or another backend secret in frontend code or configuration.

## Local Development

Run FastAPI and Next.js independently. From the repository root, start the backend with `uvicorn api.main:app --reload`. From `frontend/`, run `npm install` and `npm run dev`. Copy `frontend/.env.local.example` to `.env.local` to configure `NEXT_PUBLIC_API_BASE_URL`; configure `CARGOAI_FRONTEND_ORIGIN` in the backend environment if the frontend uses a different origin.

## Verification

- Unit-test the API health response, empty/whitespace and over-limit input rejection, and allowed/disallowed CORS origins.
- Test the frontend request helper for endpoint selection, exact JSON payload, empty/over-limit validation, backend errors, and unavailable API handling.
- Build the Next.js application.
- Run local integration checks for health and one request through each extraction endpoint. Confirm empty and over-limit requests fail with HTTP 400 and the UI reports an unavailable backend clearly.
- Inspect changed files to confirm parser modules, schemas, evaluators, and benchmark data are untouched.
