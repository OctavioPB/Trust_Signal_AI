/**
 * Main session analysis view.
 *
 * All back-end behaviour — token fetch, polling, demo store, PDF download —
 * is unchanged from the previous version. Only the visual composition and
 * markup were re-laid for the OPB system.
 *
 * Layout:
 *   <Sidebar>  ←  sticky left rail (session credentials, polling, demo)
 *   <main>
 *     <Hero>           — dark navy + grid + TrustScore gauge
 *     <KpiRow>         — four stat cards
 *     <Signal section> — list + donut, two-column
 *     <AlertPanel>     — only when flagged
 *     <TranscriptView> — heat-bar per candidate turn
 *     <PdfButton>      — gold CTA, hidden in demo mode
 *   </main>
 */

import { useEffect, useState } from "react";

import { AlertPanel } from "../components/AlertPanel";
import { Eyebrow } from "../components/Eyebrow";
import { KpiRow } from "../components/KpiRow";
import { Sidebar } from "../components/Sidebar";
import { SignalBreakdownChart } from "../components/SignalBreakdownChart";
import { TranscriptView } from "../components/TranscriptView";
import { TrustScoreGauge } from "../components/TrustScoreGauge";

import { usePolling } from "../hooks/usePolling";
import { ApiError, getReport, getReportPdf, getToken } from "../services/api";
import { useDemoStore } from "../stores/demoStore";
import type { ReportResponse } from "../types";

// ─── Helpers ────────────────────────────────────────────────────────────────

function fmtDuration(start?: number, end?: number | null): string {
  if (start === undefined) return "—";
  const seconds = Math.max(0, (end ?? Math.floor(Date.now() / 1000)) - start);
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

function relTime(ts?: number): string {
  if (ts === undefined) return "—";
  const d = Math.floor(Date.now() / 1000) - ts;
  if (d < 60) return `${d}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// ─── Sub-components private to this page ────────────────────────────────────

function Hero({
  data,
  polling,
  onTogglePolling,
  isDemo,
}: {
  data: ReportResponse;
  polling: boolean;
  onTogglePolling: () => void;
  isDemo: boolean;
}) {
  const isLive = data.status === "live";
  return (
    <section className="hero">
      <div className="hero-top">
        <div className="hero-id">
          <Eyebrow variant="dark">
            Session Analysis · {relTime(data.start_ts)}
          </Eyebrow>
          <code className="session-id">#{data.session_id}</code>
          {isLive && (
            <span className="badge live">
              <span className="dot" />
              Live · {fmtDuration(data.start_ts, data.end_ts)}
            </span>
          )}
          {isDemo && (
            <span className="badge dark">
              <span className="dot" />
              Demo
            </span>
          )}
        </div>
        <div className="hero-actions">
          <button className="btn btn-ghost-dark" onClick={onTogglePolling}>
            {polling ? "⏸ Pause polling" : "▶ Resume polling"}
          </button>
        </div>
      </div>

      <div className="hero-body">
        <div>
          <h1>
            Interview <em>authenticity</em>
          </h1>
          <p className="lede">
            Five signal modules, weighted into one explainable TrustScore.
            Delivered within 60 s of call end — with the full reasoning chain
            attached.
          </p>

          <div className="meta-strip">
            <div className="meta-cell">
              <div className="lbl">Recruiter</div>
              <div className="val">{data.recruiter_id.slice(0, 8) || "—"}</div>
            </div>
            <div className="meta-cell">
              <div className="lbl">Started</div>
              <div className="val">{fmtDate(data.start_ts)}</div>
            </div>
            <div className="meta-cell">
              <div className="lbl">Duration</div>
              <div className="val">
                {fmtDuration(data.start_ts, data.end_ts)}
              </div>
            </div>
            <div className="meta-cell">
              <div className="lbl">Status</div>
              <div className="val">{data.status.toUpperCase()}</div>
            </div>
          </div>
        </div>

        <TrustScoreGauge trustScore={data.trust_score} />
      </div>
    </section>
  );
}

function ClearedCallout({ data }: { data: ReportResponse }) {
  const top = [...data.signals]
    .sort((a, b) => a.raw_score - b.raw_score)
    .slice(0, 3);
  return (
    <div className="alert clear">
      <div className="alert-head">
        <h3>
          Session <em>cleared</em>
        </h3>
        <span className="badge success">
          <span className="dot" />
          No flags
        </span>
      </div>
      <p className="reason">
        All five signal modules returned scores below their high-risk
        thresholds. Suspicion index <b>{data.suspicion_index.toFixed(3)}</b>{" "}
        sits under the decision threshold of 0.65. No reviewer action required.
      </p>
      <div className="factors">
        {top.map((s) => (
          <div className="factor" key={s.signal_name}>
            <div className="dot" style={{ background: "var(--verde)" }} />
            <div className="text">
              <b>{s.signal_name}</b>
              {s.explanation}
            </div>
            <div className="v">{s.raw_score.toFixed(2)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export function SessionPage() {
  const [recruiterId, setRecruiterId] = useState("");
  const [sessionId, setSessionId]     = useState("");
  const [token, setToken]             = useState<string | null>(null);
  const [report, setReport]           = useState<ReportResponse | null>(null);
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState<string | null>(null);
  const [polling, setPolling]         = useState(false);

  const { isDemo, scenario, setDemo } = useDemoStore();

  const { data: pollData, isPolling } = usePolling(
    sessionId,
    10_000,
    polling && !isDemo,
    token,
  );

  useEffect(() => {
    if (!pollData) return;
    setReport((prev) =>
      prev
        ? {
            ...prev,
            trust_score:     pollData.trust_score,
            suspicion_index: pollData.suspicion_index,
            flagged:         pollData.flagged,
            flag_reason:     pollData.flag_reason,
            status:          pollData.status,
            signals:         pollData.signals,
          }
        : prev,
    );
    if (pollData.status !== "live") setPolling(false);
  }, [pollData]);

  useEffect(() => {
    if (!isPolling && polling) setPolling(false);
  }, [isPolling, polling]);

  const displayData: ReportResponse | null = isDemo ? scenario : report;

  async function handleLoadSession() {
    setError(null);
    setLoading(true);
    setDemo(false);
    try {
      const tok = await getToken(recruiterId);
      setToken(tok.access_token);
      const r = await getReport(tok.access_token, sessionId);
      setReport(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function handleLoadDemo() {
    setError(null);
    setPolling(false);
    setDemo(true);
  }

  async function handleDownloadPdf() {
    if (isDemo || !token || !sessionId) return;
    try {
      const blob = await getReportPdf(token, sessionId);
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = `trustsignal_${sessionId.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  const pdfBtnDisabled = isDemo || !token || !sessionId;

  return (
    <div className="page">
      <Sidebar
        recruiterId={recruiterId}
        sessionId={sessionId}
        polling={polling}
        loading={loading}
        onRecruiterIdChange={setRecruiterId}
        onSessionIdChange={setSessionId}
        onLoadSession={handleLoadSession}
        onLoadDemo={handleLoadDemo}
        onPollingToggle={() => setPolling((p) => !p)}
      />

      <main className="main">
        {/* ── Error banner ──────────────────────────────────────── */}
        {error && (
          <div className="banner banner-error" role="alert">
            <span className="badge danger">
              <span className="dot" />
              Error
            </span>
            <span>{error}</span>
          </div>
        )}

        {/* ── Empty state ──────────────────────────────────────── */}
        {!displayData && !error && (
          <div className="empty">
            <h2>
              No session <em>loaded.</em>
            </h2>
            <p>
              Enter a Recruiter ID and Session ID, then click{" "}
              <strong>Load Session</strong> — or click <strong>Load Demo</strong>{" "}
              to explore a synthetic flagged session.
            </p>
            <div className="empty-actions">
              <button className="btn btn-primary" onClick={handleLoadDemo}>
                Load Demo
              </button>
            </div>
          </div>
        )}

        {/* ── Loaded session ───────────────────────────────────── */}
        {displayData && (
          <>
            <Hero
              data={displayData}
              polling={polling}
              onTogglePolling={() => setPolling((p) => !p)}
              isDemo={isDemo}
            />

            <section className="section">
              <div className="section-head">
                <div className="titles">
                  <Eyebrow>01 · Key Metrics</Eyebrow>
                  <h2>
                    Weighted aggregate <em>at a glance</em>
                  </h2>
                  <p className="lead">
                    Top-line numbers from the current session — TrustScore,
                    suspicion index, flag status, and conversation depth.
                  </p>
                </div>
                <div className="actions">
                  <span className="badge info">
                    <span className="dot" />
                    Updated {relTime(displayData.start_ts)}
                  </span>
                </div>
              </div>
              <KpiRow data={displayData} />
            </section>

            <section className="section">
              <div className="section-head">
                <div className="titles">
                  <Eyebrow>02 · Signal Breakdown</Eyebrow>
                  <h2>
                    Five modules, <em>weighted into one score</em>
                  </h2>
                  <p className="lead">
                    Raw suspicion scores per module (coloured by tier) and how
                    each module contributes to the aggregate index.
                  </p>
                </div>
              </div>
              <SignalBreakdownChart
                signals={displayData.signals}
                suspicionIndex={displayData.suspicion_index}
              />
            </section>

            {/* Alert (flagged) or cleared callout */}
            <section className="section">
              {displayData.flagged ? (
                <AlertPanel
                  flagged={displayData.flagged}
                  flagReason={displayData.flag_reason}
                  signals={displayData.signals}
                />
              ) : (
                <ClearedCallout data={displayData} />
              )}
            </section>

            {displayData.turns.length > 0 && (
              <section className="section">
                <div className="section-head">
                  <div className="titles">
                    <Eyebrow>03 · Transcript</Eyebrow>
                    <h2>
                      Per-turn <em>suspicion heat-map</em>
                    </h2>
                    <p className="lead">
                      Each candidate turn is scored independently. The colour
                      bar on the left grows in saturation as suspicion rises.
                    </p>
                  </div>
                </div>
                <TranscriptView
                  turns={displayData.turns as Array<{
                    speaker: string;
                    text: string;
                    suspicion_score?: number;
                  }>}
                />
              </section>
            )}

            {!isDemo && (
              <div className="pdf-cta">
                <button
                  className="btn btn-gold"
                  onClick={handleDownloadPdf}
                  disabled={pdfBtnDisabled}
                >
                  ↓ Download PDF Report
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
