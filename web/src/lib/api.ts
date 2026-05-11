import type {
  CampaignBrief,
  RunMode,
  RunSummary,
  StartRunResponse,
} from "@/types/api";
import { getCredentials } from "@/lib/credentials";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function jsonRequest<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new ApiError(
      text || `Request to ${input} failed: ${response.status}`,
      response.status,
    );
  }
  return (await response.json()) as T;
}

export async function startRun(
  brief: CampaignBrief,
  mode: RunMode,
): Promise<StartRunResponse> {
  const credentials = getCredentials();
  const payload: Record<string, unknown> = { brief, mode };
  if (credentials) {
    payload.provider = credentials.provider;
    payload.api_key = credentials.apiKey;
  }
  return jsonRequest<StartRunResponse>("/api/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listRuns(): Promise<RunSummary[]> {
  return jsonRequest<RunSummary[]>("/api/runs");
}

/**
 * Build a URL to a run's artifact file. The backend's events stream emits
 * full disk paths (e.g. `outputs/<run_id>/index.html`) — we strip everything
 * up to the run_id and serve via the safe `/api/runs/:id/files/:filename`
 * endpoint, which only allows .png/.jpg/.jpeg/.html/.json suffixes.
 */
export function fileUrl(runId: string, fullPath: string | null | undefined): string | null {
  if (!fullPath) return null;
  // Normalize Windows-style separators just in case.
  const normalized = fullPath.replace(/\\/g, "/");
  const segments = normalized.split("/");
  const basename = segments[segments.length - 1];
  if (!basename) return null;
  return `/api/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(basename)}`;
}

export function eventStreamUrl(runId: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/events`;
}

export function packageZipUrl(runId: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/package.zip`;
}
