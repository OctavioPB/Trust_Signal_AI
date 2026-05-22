/**
 * TrustSignal AI — plain fetch wrapper.
 * All requests go through Vite's /api proxy → http://localhost:8000 in dev.
 * Throws ApiError on non-2xx responses.
 */

import type {
  ReportResponse,
  ScoreResponse,
  SessionEndResponse,
  SessionStartResponse,
  SignalScoresRequest,
  TokenResponse,
} from "../types";

const BASE = "/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function _request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore JSON parse failure
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export async function healthCheck(): Promise<{ status: string; version: string }> {
  return _request("/health");
}

export async function getToken(recruiterId: string): Promise<TokenResponse> {
  return _request("/auth/token", {
    method: "POST",
    body: JSON.stringify({ recruiter_id: recruiterId }),
  });
}

export async function startSession(
  token: string,
  recruiterId: string,
  candidateId: string,
): Promise<SessionStartResponse> {
  return _request("/session/start", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ recruiter_id: recruiterId, candidate_id: candidateId }),
  });
}

export async function submitSignals(
  token: string,
  sessionId: string,
  scores: SignalScoresRequest,
): Promise<ScoreResponse> {
  return _request(`/session/${sessionId}/signals`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(scores),
  });
}

export async function getScore(
  token: string,
  sessionId: string,
): Promise<ScoreResponse> {
  return _request(`/session/${sessionId}/score`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function getReport(
  token: string,
  sessionId: string,
): Promise<ReportResponse> {
  return _request(`/session/${sessionId}/report`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function endSession(
  token: string,
  sessionId: string,
): Promise<SessionEndResponse> {
  return _request(`/session/${sessionId}/end`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function deleteSession(
  token: string,
  sessionId: string,
): Promise<{ session_id: string; deleted: boolean; audio_objects_removed: number }> {
  return _request(`/session/${sessionId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function getReportPdf(token: string, sessionId: string): Promise<Blob> {
  const res = await fetch(`${BASE}/session/${sessionId}/report/pdf`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail);
  }
  return res.blob();
}
