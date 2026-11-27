/**
 * usePolling — auto-refreshes the score endpoint at a fixed interval.
 *
 * Stops automatically when session status leaves "live".
 * Clears the interval on unmount (no stale closure leaks).
 */

import { useEffect, useState } from "react";
import { ApiError, getScore } from "../services/api";
import type { ScoreResponse } from "../types";

interface PollingResult {
  data: ScoreResponse | null;
  error: string | null;
  isPolling: boolean;
}

export function usePolling(
  sessionId: string,
  interval: number,
  enabled: boolean,
  token: string | null,
): PollingResult {
  const [data, setData]       = useState<ScoreResponse | null>(null);
  const [error, setError]     = useState<string | null>(null);
  // Set when the session leaves "live"; reset whenever the polling inputs change.
  const [stopped, setStopped] = useState(false);

  const active = enabled && !!token && !!sessionId;

  useEffect(() => {
    if (!active) return;

    const timer = setInterval(async () => {
      try {
        const score = await getScore(token!, sessionId);
        setData(score);
        setError(null);
        if (score.status !== "live") {
          clearInterval(timer);
          setStopped(true);
        }
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Polling error");
      }
    }, interval);

    return () => {
      clearInterval(timer);
      setStopped(false);
    };
  }, [active, token, sessionId, interval]);

  // Derived, so it is accurate on the same render that enables polling.
  return { data, error, isPolling: active && !stopped };
}
