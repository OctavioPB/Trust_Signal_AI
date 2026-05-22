/**
 * Vitest unit tests for api.ts.
 *
 * Strategy: vi.stubGlobal("fetch", ...) replaces the global fetch with a
 * configurable mock. Each test asserts the correct URL, method, headers,
 * and body — and that ApiError is thrown on non-2xx responses.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  deleteSession,
  endSession,
  getReport,
  getReportPdf,
  getScore,
  getToken,
  healthCheck,
  startSession,
  submitSignals,
} from "./api";

// ── Helpers ─────────────────────────────────────────────────────────────────

function mockFetch(body: unknown, status = 200): void {
  const isBlob = body instanceof Blob;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      statusText: status === 200 ? "OK" : "Error",
      json: isBlob ? () => Promise.resolve({}) : () => Promise.resolve(body),
      blob: () => Promise.resolve(isBlob ? body : new Blob()),
    }),
  );
}

function lastCall(): { url: string; init: RequestInit } {
  const mock = vi.mocked(fetch);
  const [url, init] = mock.mock.calls[0] as [string, RequestInit];
  return { url, init: init ?? {} };
}

const TOKEN = "test-jwt-token";
const SESSION = "session-uuid-1234";
const RECRUITER = "recruiter-uuid-5678";
const CANDIDATE = "candidate-uuid-9012";

// ── Setup / teardown ─────────────────────────────────────────────────────────

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── healthCheck ──────────────────────────────────────────────────────────────

describe("healthCheck", () => {
  it("calls GET /api/health", async () => {
    mockFetch({ status: "ok", version: "0.7.0" });
    await healthCheck();
    expect(lastCall().url).toBe("/api/health");
    expect(lastCall().init.method).toBeUndefined();
  });

  it("returns the response body", async () => {
    mockFetch({ status: "ok", version: "0.7.0" });
    const result = await healthCheck();
    expect(result.status).toBe("ok");
  });
});

// ── getToken ─────────────────────────────────────────────────────────────────

describe("getToken", () => {
  it("calls POST /api/auth/token with recruiter_id body", async () => {
    mockFetch({ access_token: TOKEN, token_type: "bearer", expires_in_hours: 24 });
    await getToken(RECRUITER);
    const { url, init } = lastCall();
    expect(url).toBe("/api/auth/token");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ recruiter_id: RECRUITER });
  });
});

// ── startSession ─────────────────────────────────────────────────────────────

describe("startSession", () => {
  it("sends bearer token and correct body", async () => {
    mockFetch({ session_id: SESSION, status: "live", start_ts: 0 });
    await startSession(TOKEN, RECRUITER, CANDIDATE);
    const { url, init } = lastCall();
    expect(url).toBe("/api/session/start");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Authorization"]).toBe(`Bearer ${TOKEN}`);
    expect(JSON.parse(init.body as string)).toEqual({
      recruiter_id: RECRUITER,
      candidate_id: CANDIDATE,
    });
  });
});

// ── submitSignals ─────────────────────────────────────────────────────────────

describe("submitSignals", () => {
  it("calls POST /api/session/:id/signals", async () => {
    mockFetch({ session_id: SESSION, status: "live", trust_score: 75, suspicion_index: 0.25, flagged: false, flag_reason: "", signals: [] });
    const scores = { latency_score: 0.2, burstiness_score: 0.3 };
    await submitSignals(TOKEN, SESSION, scores);
    const { url, init } = lastCall();
    expect(url).toBe(`/api/session/${SESSION}/signals`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toMatchObject(scores);
  });
});

// ── getScore ─────────────────────────────────────────────────────────────────

describe("getScore", () => {
  it("calls GET /api/session/:id/score with bearer token", async () => {
    mockFetch({ session_id: SESSION, status: "live", trust_score: 80, suspicion_index: 0.2, flagged: false, flag_reason: "", signals: [] });
    await getScore(TOKEN, SESSION);
    const { url, init } = lastCall();
    expect(url).toBe(`/api/session/${SESSION}/score`);
    expect((init.headers as Record<string, string>)["Authorization"]).toBe(`Bearer ${TOKEN}`);
  });
});

// ── getReport ─────────────────────────────────────────────────────────────────

describe("getReport", () => {
  it("calls GET /api/session/:id/report", async () => {
    mockFetch({ session_id: SESSION, recruiter_id: RECRUITER, status: "completed", start_ts: 0, end_ts: 1, trust_score: 72, suspicion_index: 0.28, flagged: false, flag_reason: "", signals: [], turns: [] });
    await getReport(TOKEN, SESSION);
    expect(lastCall().url).toBe(`/api/session/${SESSION}/report`);
  });
});

// ── endSession ────────────────────────────────────────────────────────────────

describe("endSession", () => {
  it("calls POST /api/session/:id/end", async () => {
    mockFetch({ session_id: SESSION, status: "completed", trust_score: 72, flagged: false, flag_reason: "" });
    await endSession(TOKEN, SESSION);
    const { url, init } = lastCall();
    expect(url).toBe(`/api/session/${SESSION}/end`);
    expect(init.method).toBe("POST");
  });
});

// ── deleteSession ─────────────────────────────────────────────────────────────

describe("deleteSession", () => {
  it("calls DELETE /api/session/:id", async () => {
    mockFetch({ session_id: SESSION, deleted: true, audio_objects_removed: 0 });
    await deleteSession(TOKEN, SESSION);
    const { url, init } = lastCall();
    expect(url).toBe(`/api/session/${SESSION}`);
    expect(init.method).toBe("DELETE");
  });
});

// ── getReportPdf ──────────────────────────────────────────────────────────────

describe("getReportPdf", () => {
  it("calls GET /api/session/:id/report/pdf and returns a Blob", async () => {
    const fakePdf = new Blob(["%PDF-1.4"], { type: "application/pdf" });
    mockFetch(fakePdf);
    const result = await getReportPdf(TOKEN, SESSION);
    expect(lastCall().url).toBe(`/api/session/${SESSION}/report/pdf`);
    expect(result).toBeInstanceOf(Blob);
  });
});

// ── ApiError ──────────────────────────────────────────────────────────────────

describe("ApiError", () => {
  it("is thrown on 401 responses", async () => {
    mockFetch({ detail: "Invalid or expired authentication token." }, 401);
    await expect(getScore(TOKEN, SESSION)).rejects.toBeInstanceOf(ApiError);
  });

  it("carries the HTTP status code", async () => {
    mockFetch({ detail: "Session not found." }, 404);
    try {
      await getReport(TOKEN, SESSION);
      expect.fail("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(404);
    }
  });

  it("carries the detail message from JSON body", async () => {
    mockFetch({ detail: "Session not found." }, 404);
    try {
      await getReport(TOKEN, SESSION);
    } catch (e) {
      expect((e as ApiError).message).toBe("Session not found.");
    }
  });

  it("falls back to statusText when body has no detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: () => Promise.reject(new SyntaxError("not JSON")),
        blob: () => Promise.resolve(new Blob()),
      }),
    );
    try {
      await healthCheck();
    } catch (e) {
      expect((e as ApiError).message).toBe("Internal Server Error");
    }
  });
});
