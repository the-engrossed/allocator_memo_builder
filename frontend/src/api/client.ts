import type { AnalysisResponse } from "../types/api";

async function readError(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (
      payload &&
      typeof payload === "object" &&
      "detail" in payload &&
      typeof payload.detail === "string"
    ) {
      return payload.detail;
    }
  } catch {
    // Fall through to status text when the body is not JSON.
  }
  return response.statusText || "Request failed";
}

export async function uploadAnalysis(file: File): Promise<AnalysisResponse> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/analyses", {
    method: "POST",
    body,
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as AnalysisResponse;
}
