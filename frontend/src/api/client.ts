import type {
  AnalysisResponse,
  EvidenceRecord,
  EvidenceRegistryResponse,
  MandatePayload,
  MandateResponse,
  MemoResponse,
  MemoSummary,
  RankingRunResponse,
} from "../types/api";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    /** Machine-readable code when the backend returns `detail: {code, message}`. */
    readonly code: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ErrorBody {
  message: string;
  code: string | null;
}

async function readError(response: Response): Promise<ErrorBody> {
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === "object" && "detail" in payload) {
      const { detail } = payload;
      if (typeof detail === "string") {
        return { message: detail, code: null };
      }
      if (Array.isArray(detail)) {
        return { message: detail.map(formatValidationError).join("; "), code: null };
      }
      if (detail && typeof detail === "object") {
        const code = "code" in detail && typeof detail.code === "string" ? detail.code : null;
        const message =
          "message" in detail && typeof detail.message === "string"
            ? detail.message
            : response.statusText || "Request failed";
        return { message, code };
      }
    }
  } catch {
    // Fall through to status text when the body is not JSON.
  }
  return { message: response.statusText || "Request failed", code: null };
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

async function failure(response: Response): Promise<ApiError> {
  const { message, code } = await readError(response);
  return new ApiError(response.status, message, code);
}

export async function uploadAnalysis(file: File): Promise<AnalysisResponse> {
  const body = new FormData();
  body.append("file", file);
  const response = await send("/api/analyses", {
    method: "POST",
    body,
  });
  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as AnalysisResponse;
}

function analysisUrl(analysisId: string, path: string): string {
  return `/api/analyses/${encodeURIComponent(analysisId)}/${path}`;
}

/** Returns the saved mandate, or null when the analysis exists but has no mandate yet. */
export async function getMandate(analysisId: string): Promise<MandateResponse | null> {
  const response = await send(analysisUrl(analysisId, "mandate"));
  if (response.ok) {
    return (await response.json()) as MandateResponse;
  }
  const error = await failure(response);
  if (error.status === 404 && error.code === "NO_MANDATE") {
    return null;
  }
  throw error;
}

export async function putMandate(
  analysisId: string,
  mandate: MandatePayload,
): Promise<MandateResponse> {
  const response = await send(analysisUrl(analysisId, "mandate"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mandate),
  });
  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as MandateResponse;
}

/** Returns the most recent ranking run, or null when the analysis has none yet. */
export async function getLatestRankingRun(analysisId: string): Promise<RankingRunResponse | null> {
  const response = await send(analysisUrl(analysisId, "ranking-runs/latest"));
  if (response.ok) {
    return (await response.json()) as RankingRunResponse;
  }
  const error = await failure(response);
  if (error.status === 404 && error.code === "NO_RANKING_RUN") {
    return null;
  }
  throw error;
}

/** Creates a new immutable ranking run; every call is a new run. */
export async function createRankingRun(analysisId: string): Promise<RankingRunResponse> {
  const response = await send(analysisUrl(analysisId, "ranking-runs"), { method: "POST" });
  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as RankingRunResponse;
}

export async function getAnalysis(analysisId: string): Promise<AnalysisResponse> {
  const response = await send(`/api/analyses/${encodeURIComponent(analysisId)}`);
  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as AnalysisResponse;
}

function runUrl(runId: string, path: string): string {
  return `/api/ranking-runs/${encodeURIComponent(runId)}/${path}`;
}

/** The run's evidence registry, rebuilt from the immutable run (Analysis page drawer). */
export async function getRunEvidence(runId: string): Promise<EvidenceRecord[]> {
  const response = await send(runUrl(runId, "evidence"));
  if (!response.ok) {
    throw await failure(response);
  }
  return ((await response.json()) as EvidenceRegistryResponse).records;
}

/** Latest memo revision for the run, or null when none has been generated yet. */
export async function getLatestMemo(runId: string): Promise<MemoResponse | null> {
  const response = await send(runUrl(runId, "memos/latest"));
  if (response.ok) {
    return (await response.json()) as MemoResponse;
  }
  const error = await failure(response);
  if (error.status === 404 && error.code === "NO_MEMO") {
    return null;
  }
  throw error;
}

export async function listMemos(runId: string): Promise<MemoSummary[]> {
  const response = await send(runUrl(runId, "memos"));
  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as MemoSummary[];
}

export async function getMemo(memoId: string): Promise<MemoResponse> {
  const response = await send(`/api/memos/${encodeURIComponent(memoId)}`);
  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as MemoResponse;
}

/** Creates a new memo revision. 409 MEMO_IN_PROGRESS means another request took the revision. */
export async function createMemo(
  runId: string,
  mode: "auto" | "template" = "auto",
): Promise<MemoResponse> {
  const response = await send(runUrl(runId, "memos"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!response.ok) {
    throw await failure(response);
  }
  return (await response.json()) as MemoResponse;
}
