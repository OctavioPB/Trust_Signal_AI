/**
 * usePolling — auto-refreshes the score endpoint at a fixed interval.
 *
 * Stops automatically when session status leaves "live".
 * Clears the interval on unmount (no stale closure leaks).
 */

import { useEffect, useRef, useState } from "react";
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
  const [isPolling, setIsPolling] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setIsPolling(false);

    if (!enabled || !token || !sessionId) return;

    setIsPolling(true);

    timerRef.current = setInterval(async () => {
      try {
        const score = await getScore(token, sessionId);
        setData(score);
        setError(null);
        if (score.status !== "live") {
          clearInterval(timerRef.current!);
          timerRef.current = null;
          setIsPolling(false);
        }
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Polling error");
      }
    }, interval);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      setIsPolling(false);
    };
  }, [enabled, token, sessionId, interval]);

  return { data, error, isPolling };
}
