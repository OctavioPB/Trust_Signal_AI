/**
 * Main session analysis view.
 *
 * Layout: Sidebar (left) + scrollable main content (right).
 * Data source: demoStore when isDemo=true, else live FastAPI calls.
 * Polling: usePolling hook (10 s interval) while session status is "live".
 *
 * PDF download: disabled in demo mode — requires a real session token.
 * Blob flow: getReportPdf → URL.createObjectURL → programmatic <a> click → revokeObjectURL.
 */

import { useEffect, useState } from "react";
import { AlertPanel } from "../components/AlertPanel";
import { KpiRow } from "../components/KpiRow";
import { Sidebar } from "../components/Sidebar";
import { SignalBreakdownChart } from "../components/SignalBreakdownChart";
import { TranscriptView } from "../components/TranscriptView";
import { TrustScoreGauge } from "../components/TrustScoreGauge";
import { usePolling } from "../hooks/usePolling";
import { ApiError, getReport, getReportPdf, getToken } from "../services/api";
import { useDemoStore } from "../stores/demoStore";
import type { ReportResponse } from "../types";

// ── Eyebrow label (BRAND.md signature element) ─────────────────────────────
function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 9, fontFamily: "var(--fb)", fontWeight: 500, letterSpacing: "4px", textTransform: "uppercase", color: "var(--gold)", marginBottom: 10 }}>
      <div style={{ width: 24, height: 1, flexShrink: 0, backgroundColor: "var(--gold)" }} />
      {children}
    </div>
  );
}

function Section({ eyebrow, children }: { eyebrow: string; children: React.ReactNode }) {
  return (
    <section>
      <Eyebrow>{eyebrow}</Eyebrow>
      {children}
    </section>
  );
}

export function SessionPage() {
  const [apiUrl, setApiUrl]           = useState("http://localhost:8000");
  const [recruiterId, setRecruiterId] = useState("");
  const [sessionId, setSessionId]     = useState("");
  const [token, setToken]             = useState<string | null>(null);
  const [report, setReport]           = useState<ReportResponse | null>(null);
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState<string | null>(null);
  const [polling, setPolling]         = useState(false);

  const { isDemo, scenario, setDemo } = useDemoStore();

  // 13.1 — usePolling hook replaces inline setInterval/useRef pattern
  const { data: pollData, isPolling } = usePolling(
    sessionId,
    10_000,
    polling && !isDemo,
    token,
  );

  // Merge polling score updates into the full report state
  useEffect(() => {
    if (!pollData) return;
    setReport(prev =>
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

  // Sync sidebar polling indicator with hook state
  useEffect(() => {
    if (!isPolling && polling) setPolling(false);
  }, [isPolling, polling]);

  const displayData: ReportResponse | null = isDemo ? scenario : report;

  // ── Load session ────────────────────────────────────────────────────────
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

  // 13.2 — PDF download; disabled in demo mode (no real token/session)
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

  // ── Styles ──────────────────────────────────────────────────────────────
  const layout: React.CSSProperties = {
    display: "flex",
    minHeight: "calc(100vh - 52px)",
    alignItems: "stretch",
  };

  const main: React.CSSProperties = {
    flex: 1,
    padding: "32px 40px",
    display: "flex",
    flexDirection: "column",
    gap: 32,
    maxWidth: 1040,
    minWidth: 0,
  };

  const pdfBtnDisabled = isDemo || !token || !sessionId;
  const pdfBtn: React.CSSProperties = {
    alignSelf: "flex-start",
    padding: "9px 20px",
    backgroundColor: "var(--primary)",
    border: "none",
    borderRadius: 8,
    color: "var(--white)",
    fontFamily: "var(--fb)",
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: "1.5px",
    textTransform: "uppercase",
    cursor: pdfBtnDisabled ? "not-allowed" : "pointer",
    opacity: pdfBtnDisabled ? 0.4 : 1,
  };

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <div style={layout}>
      <Sidebar
        apiUrl={apiUrl}
        recruiterId={recruiterId}
        sessionId={sessionId}
        polling={polling}
        loading={loading}
        onApiUrlChange={setApiUrl}
        onRecruiterIdChange={setRecruiterId}
        onSessionIdChange={setSessionId}
        onLoadSession={handleLoadSession}
        onLoadDemo={handleLoadDemo}
        onPollingToggle={() => setPolling(p => !p)}
      />

      <main style={main}>
        {/* Hero banner — dark, grid texture, gauge embedded */}
        <div style={{
          backgroundColor: "var(--primary)",
          backgroundImage: `linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px)`,
          backgroundSize: "48px 48px",
          borderRadius: 14,
          padding: "32px 40px",
          display: "flex",
          alignItems: "center",
          gap: 40,
        }}>
          <div style={{ flexShrink: 0, width: 220 }}>
            <TrustScoreGauge trustScore={displayData?.trust_score ?? 0} />
          </div>
          <div>
            <div style={{ fontFamily: "var(--fb)", fontSize: 9, letterSpacing: "4px", textTransform: "uppercase", color: "var(--gold-light)", marginBottom: 10 }}>
              Interview Authenticity
            </div>
            <h1 style={{ fontFamily: "Fraunces, Georgia, serif", fontSize: 28, fontWeight: 300, color: "#ffffff", margin: 0, lineHeight: 1.3 }}>
              {displayData
                ? <>Session <em style={{ fontStyle: "italic", color: "var(--gold-light)" }}>{displayData.session_id.slice(0, 8)}</em></>
                : <em style={{ fontStyle: "italic", color: "rgba(255,255,255,0.4)" }}>No session loaded</em>
              }
            </h1>
            {displayData && (
              <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "rgba(255,255,255,0.6)", marginTop: 10, lineHeight: 1.65 }}>
                Recruiter&nbsp;
                <code style={{ fontSize: 11, color: "rgba(255,255,255,0.4)" }}>
                  {displayData.recruiter_id.slice(0, 8)}…
                </code>
                &emsp;·&emsp;
                {new Date(displayData.start_ts * 1000).toLocaleString()}
                {isDemo && (
                  <span style={{ marginLeft: 12, backgroundColor: "rgba(200,152,42,0.2)", color: "var(--gold-light)", borderRadius: 4, padding: "2px 8px", fontSize: 9, fontWeight: 700, letterSpacing: "2px", textTransform: "uppercase" }}>
                    DEMO
                  </span>
                )}
              </p>
            )}
          </div>
        </div>

        {error && (
          <div style={{ backgroundColor: "var(--red-bg)", border: "1px solid var(--red)", borderRadius: 8, padding: "12px 16px", fontFamily: "var(--fb)", fontSize: 13, color: "var(--red)" }}>
            {error}
          </div>
        )}

        {!displayData && !error && (
          <div style={{ textAlign: "center", padding: "48px 0" }}>
            <p style={{ fontFamily: "var(--fb)", fontSize: 14, color: "var(--mid)" }}>
              Enter a session ID and click <strong>Load Session</strong>, or click <strong>Load Demo</strong> to explore a synthetic flagged session.
            </p>
          </div>
        )}

        {displayData && (
          <Section eyebrow="Key Metrics">
            <KpiRow data={displayData} />
          </Section>
        )}

        {displayData && (
          <Section eyebrow="Signal Breakdown">
            <div style={{ backgroundColor: "var(--white)", borderRadius: 12, boxShadow: "var(--shadow-card)", padding: "20px 24px" }}>
              <SignalBreakdownChart signals={displayData.signals} />
            </div>
          </Section>
        )}

        {displayData && (
          <AlertPanel
            flagged={displayData.flagged}
            flagReason={displayData.flag_reason}
            signals={displayData.signals}
          />
        )}

        {displayData && displayData.turns.length > 0 && (
          <Section eyebrow="Transcript">
            <TranscriptView
              turns={displayData.turns as Array<{ speaker: string; text: string; suspicion_score?: number }>}
            />
          </Section>
        )}

        {/* PDF download — hidden in demo mode (no real token) */}
        {displayData && !isDemo && (
          <div>
            <button style={pdfBtn} onClick={handleDownloadPdf} disabled={pdfBtnDisabled}>
              ↓ Download PDF Report
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
