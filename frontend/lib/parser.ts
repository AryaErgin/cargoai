export type ParserKind = "spot" | "tender";

export const MAX_INPUT_LENGTH = 20_000;

type ParserResponse = {
  result?: unknown;
  detail?: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function requestExtraction(
  kind: ParserKind,
  text: string,
  fetcher: typeof fetch = fetch,
): Promise<Record<string, unknown>> {
  if (!text.trim()) {
    throw new Error("Enter text before extracting.");
  }
  if (text.length > MAX_INPUT_LENGTH) {
    throw new Error("Text must be 20,000 characters or fewer.");
  }

  const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(
    /\/+$/,
    "",
  );

  let response: Response;
  try {
    response = await fetcher(`${apiBaseUrl}/parse/${kind}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      cache: "no-store",
    });
  } catch {
    throw new Error("Could not reach the API. Check that FastAPI is running.");
  }

  let payload: ParserResponse;
  try {
    payload = (await response.json()) as ParserResponse;
  } catch {
    throw new Error("The API returned an unreadable response.");
  }

  if (!response.ok) {
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      throw new Error(payload.detail);
    }
    throw new Error(`The API request failed (HTTP ${response.status}).`);
  }

  if (!isRecord(payload.result)) {
    throw new Error("The API response did not include parsed fields.");
  }

  return payload.result;
}
