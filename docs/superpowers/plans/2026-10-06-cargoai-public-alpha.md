# CargoAI Public Alpha Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a responsive, non-persistent Next.js interface for testing the existing Spot RFQ and Freight Tender parsers.

**Architecture:** Add a standalone TypeScript Next.js App Router application in `frontend/`. A single client-side page sends direct requests to the existing FastAPI routes through a small tested request helper; FastAPI allows only the configured frontend origin through CORS.

**Tech Stack:** Next.js App Router, React, TypeScript, plain CSS, Vitest, Python `unittest`, FastAPI TestClient.

**Spec:** `docs/superpowers/specs/2026-10-06-cargoai-public-alpha-design.md`

## Global Constraints

- Use `NEXT_PUBLIC_API_BASE_URL` for the browser-visible FastAPI base URL.
- Configure one `CARGOAI_FRONTEND_ORIGIN`, default `http://localhost:3000`; never use wildcard CORS or credentials.
- Reject empty or whitespace-only text and text longer than 20,000 characters in the UI; retain backend HTTP 400 validation.
- Do not add persistence, cookies, authentication, analytics, request-body logging, pricing, booking, or deployment.
- Do not modify parser modules, extraction prompts, schemas, evaluators, or benchmark data.
- Do not expose `OPENAI_API_KEY` or other backend secrets to the frontend.
- Do not commit changes; the workspace already contains unrelated uncommitted work.

## Review Focus

- Blank text with only spaces must not be submitted; the UI request helper test covers whitespace-only input and API tests cover HTTP 400.
- An input of 20,001 characters must be rejected before fetch; utility tests cover the exact limit boundary and backend tests cover HTTP 400.
- A CORS preflight from the configured frontend origin must pass while a different origin receives no allow-origin header; API tests cover both.
- `false`, `0`, null, and missing result values must render distinctly; field formatting uses `value ?? "Not provided"`, with code review and a browser smoke check covering output.
- An unavailable API or non-2xx response must produce a visible error without storing or logging input; request-helper tests cover both and the UI smoke check confirms the error state.

---

### Task 1: Restrict FastAPI CORS and pin API boundary behavior

**Files:**
- Modify: `api/main.py`
- Create: `tests/test_frontend_api_contract.py`

**Interfaces:**
- Consumes: existing `GET /health`, `POST /parse/spot`, and `POST /parse/tender` routes.
- Produces: CORS middleware allowing only `CARGOAI_FRONTEND_ORIGIN` (default `http://localhost:3000`), methods `GET` and `POST`, and the `Content-Type` request header.

- [x] **Step 1: Write the failing API contract tests**

```python
import unittest
from fastapi.testclient import TestClient
from api.main import app


class FrontendApiContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_returns_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_empty_and_oversized_text_return_400(self):
        self.assertEqual(self.client.post("/parse/spot", json={"text": "  "}).status_code, 400)
        self.assertEqual(self.client.post("/parse/tender", json={"text": "x" * 20001}).status_code, 400)

    def test_cors_allows_only_configured_frontend(self):
        allowed = self.client.options(
            "/parse/spot",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"},
        )
        denied = self.client.options(
            "/parse/spot",
            headers={"Origin": "http://example.invalid", "Access-Control-Request-Method": "POST"},
        )
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "http://localhost:3000")
        self.assertNotIn("access-control-allow-origin", denied.headers)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run the tests and confirm the CORS assertion fails**

Run: `python -m unittest discover -s tests -p test_frontend_api_contract.py -v`
Expected: health and input-validation assertions pass; allowed-origin assertion fails because the middleware is not yet configured.

- [x] **Step 3: Add narrow environment-configured CORS middleware**

Read `CARGOAI_FRONTEND_ORIGIN` once at app startup, defaulting to `http://localhost:3000`, then configure `CORSMiddleware` with that single origin, `allow_methods=["GET", "POST"]`, `allow_headers=["Content-Type"]`, and `allow_credentials=False`:

```python
frontend_origin = os.environ.get("CARGOAI_FRONTEND_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)
```

Do not change parser imports, parser calls, response shapes, or input validation.

- [x] **Step 4: Run the API contract suite**

Run: `python -m unittest discover -s tests -p test_frontend_api_contract.py -v`
Expected: all three tests pass.

### Task 2: Build the Next.js app and tested request helper

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json` via `npm install`
- Create: `frontend/tsconfig.json`
- Create: `frontend/next.config.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/.gitignore`
- Create: `frontend/.env.local.example`
- Create: `frontend/lib/parser.ts`
- Create: `frontend/lib/parser.test.ts`
- Create: `frontend/app/layout.tsx`
- Create: `frontend/app/page.tsx`
- Create: `frontend/app/page.test.tsx`
- Create: `frontend/app/globals.css`

**Interfaces:**
- Consumes: `NEXT_PUBLIC_API_BASE_URL` and the FastAPI response envelope `{ "type": string, "result": object }`.
- Produces: `requestExtraction(kind: "spot" | "tender", text: string): Promise<Record<string, unknown>>`, used by the page and Vitest tests.

- [x] **Step 1: Write request-helper tests before implementation**

Create `frontend/lib/parser.test.ts` with these checks, plus a local `jsonResponse` helper that returns a JSON `Response` with the supplied status:

```typescript
it("rejects whitespace without a request", async () => {
  const fetcher = vi.fn();
  await expect(requestExtraction("spot", "  \n", fetcher)).rejects.toThrow(/enter text/i);
  expect(fetcher).not.toHaveBeenCalled();
});

it("accepts 20,000 characters and returns the result object", async () => {
  const text = "x".repeat(20_000);
  const fetcher = vi.fn().mockResolvedValue(jsonResponse({ result: { origin: "Shanghai" } }));
  await expect(requestExtraction("spot", text, fetcher)).resolves.toEqual({ origin: "Shanghai" });
  expect(fetcher).toHaveBeenCalledWith(expect.stringMatching(/\/parse\/spot$/), expect.objectContaining({ method: "POST", body: JSON.stringify({ text }) }));
});

it.each(["spot", "tender"] as const)("selects the %s endpoint", async (kind) => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse({ result: { ok: true } }));
  await requestExtraction(kind, "RFQ", fetcher);
  expect(fetcher.mock.calls[0][0]).toMatch(new RegExp(`/parse/${kind}$`));
});

it("rejects 20,001 characters before fetch", async () => {
  const fetcher = vi.fn();
  await expect(requestExtraction("spot", "x".repeat(20_001), fetcher)).rejects.toThrow(/20,000/);
  expect(fetcher).not.toHaveBeenCalled();
});

it("uses backend detail for HTTP errors", async () => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse({ detail: "Parser unavailable" }, 502));
  await expect(requestExtraction("tender", "RFQ", fetcher)).rejects.toThrow("Parser unavailable");
});

it("reports when the API cannot be reached", async () => {
  const fetcher = vi.fn().mockRejectedValue(new TypeError("network down"));
  await expect(requestExtraction("spot", "RFQ", fetcher)).rejects.toThrow(/could not reach/i);
});
```

- [x] **Step 2: Run the helper tests and confirm they fail because the helper is missing**

Run: `npm test -- --run` from `frontend/`.
Expected: test runner starts and reports the missing `lib/parser` module or exported helper.

- [x] **Step 3: Create the minimal Next.js TypeScript scaffold and request helper**

Set scripts `dev`, `build`, `start`, and `test`. Configure Vitest for TypeScript. The helper validates text before fetch, reads `NEXT_PUBLIC_API_BASE_URL` (local fallback `http://127.0.0.1:8000`), posts JSON to `/parse/spot` or `/parse/tender`, returns `result`, uses a backend `detail` on errors, and converts fetch failures into a clear connection message.

- [x] **Step 4: Run the request-helper tests**

Run: `npm test -- --run` from `frontend/`.
Expected: all helper tests pass.

- [x] **Step 5: Build the single responsive client-side page**

Implement the header, exact subtitle/warning/privacy text, Spot RFQ and Freight Tender tabs, the supplied Spot placeholder, labeled textarea, live character count/limit, disabled/loading Extract buttons, Clear buttons, visible error region, and result cards with every field in the spec order. Use `value ?? "Not provided"` so `false` and `0` remain visible. Keep all request text in component memory only; do not add storage or logging.

- [x] **Step 6: Build the frontend**

Run: `npm run build` from `frontend/`.
Expected: Next.js compilation and static checks complete with exit code 0.

### Task 3: Document local setup and verify the complete flow

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Verify: `api/main.py`, `frontend/`, existing parser/evaluator/schema/data paths

**Interfaces:**
- Consumes: backend command `uvicorn api.main:app --reload`, frontend commands `npm install` and `npm run dev`, and `.env.local.example`.
- Produces: root README local-development instructions for starting backend and frontend independently, API base URL setup, and allowed frontend origin configuration.

- [x] **Step 1: Document setup commands and environment variables**

Add a concise Frontend section to `README.md` with backend and frontend commands, `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`, and `CARGOAI_FRONTEND_ORIGIN=http://localhost:3000`. State that the alpha submits text to the parser and users must verify results.

- [x] **Step 2: Run Python API contract tests and frontend unit tests**

Run from repository root: `python -m unittest discover -s tests -p test_frontend_api_contract.py -v`.
Run from `frontend/`: `npm test -- --run`.
Expected: both commands exit 0 with all tests passing.

- [x] **Step 3: Run one real request through each parser endpoint**

Start FastAPI with `uvicorn api.main:app --reload` and Next.js with `npm run dev`. Confirm `GET /health` returns `{"status":"ok"}`; submit one existing spot RFQ and one existing tender input through the frontend and confirm both result cards render. Do not use the source Excel workbook.

- [x] **Step 4: Verify API unavailable and input-limit UX**

Stop FastAPI and submit a valid short input; confirm a visible API-connection message. With FastAPI available, confirm blank text is not submitted and a 20,001-character input is blocked by the UI; confirm direct backend requests with empty and oversized text return HTTP 400.

- [x] **Step 5: Verify scope and privacy boundaries**

Run `git diff --check`. Inspect the final status and diff to confirm no parser, schema, evaluator, or benchmark-data path changed. Confirm no frontend storage APIs, analytics, or request-body logs were added.
