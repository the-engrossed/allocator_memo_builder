import type { AnalysisResponse, MandatePayload, MandateResponse } from "../types/api";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === "object" && "detail" in payload) {
      const { detail } = payload;
      if (typeof detail === "string") {
        return detail;
      }
      if (Array.isArray(detail)) {
        return detail.map(formatValidationError).join("; ");
      }
    }
  } catch {
    // Fall through to status text when the body is not JSON.
  }
  return response.statusText || "Request failed";
}

function formatValidationError(item: unknown): string {
  if (item && typeof item === "object" && "msg" in item && typeof item.msg === "string") {
    const location =
      "loc" in item && Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body") : [];
    return location.length > 0 ? `${location.join(".")}: ${item.msg}` : item.msg;
  }
  return "Invalid request";
}

async function send(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new ApiError(0, "Could not reach the API. Check that the backend is running.");
  }
}

export async function uploadAnalysis(file: File): Promise<AnalysisResponse> {
  const body = new FormData();
  body.append("file", file);
  const response = await send("/api/analyses", {
    method: "POST",
    body,
  });
  if (!response.ok) {
    throw new ApiError(response.status, await readError(response));
  }
  return (await response.json()) as AnalysisResponse;
}

// Temporary compatibility layer: the backend returns 404 both for an unknown analysis and for
// an analysis without a saved mandate, distinguishable only by `detail` text. Replace this
// prefix match once the API exposes a machine-readable error code.
const MANDATE_NOT_CONFIGURED_PREFIX = "Mandate not configured for analysis";

function mandateUrl(analysisId: string): string {
  return `/api/analyses/${encodeURIComponent(analysisId)}/mandate`;
}

/** Returns the saved mandate, or null when the analysis exists but has no mandate yet. */
export async function getMandate(analysisId: string): Promise<MandateResponse | null> {
  const response = await send(mandateUrl(analysisId));
  if (response.ok) {
    return (await response.json()) as MandateResponse;
  }
  const detail = await readError(response);
  if (response.status === 404 && detail.startsWith(MANDATE_NOT_CONFIGURED_PREFIX)) {
    return null;
  }
  throw new ApiError(response.status, detail);
}

export async function putMandate(
  analysisId: string,
  mandate: MandatePayload,
): Promise<MandateResponse> {
  const response = await send(mandateUrl(analysisId), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mandate),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await readError(response));
  }
  return (await response.json()) as MandateResponse;
}
