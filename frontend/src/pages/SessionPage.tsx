/**
 * Main session analysis view.
 *
 * Layout (widescreen-safe):
 *   • Full-bleed hero (dark navy + grid) — maxWidth 1300 inner container
 *   • Centered body div (maxWidth 1300) — sticky sidebar + main content column
 *
 * BRAND.md rules applied:
 *   • NO eyebrow in hero section — title starts immediately
 *   • Eyebrow light={true} on dark backgrounds, light={false} on white/light
 *   • Impact banner stat row uses borderLeft 2px #C8982A, Fraunces 34px #E8C46A
 *   • Body sections: Eyebrow + one-line description + content
 *
 * Data source: demoStore when isDemo=true, else live FastAPI via /api proxy.
 * Polling: usePolling hook (10 s) while session status is "live".
 * PDF download: disabled in demo mode — requires a real session token.
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

// ── Brand helpers ────────────────────────────────────────────────────────────

function Eyebrow({ children, light = false }: { children: React.ReactNode; light?: boolean }) {
  const color = light ? "var(--gold-light)" : "var(--gold)";
  return (
    <div style={{
      display: "inline-flex",
      alignItems: "center",
      gap: 8,
      fontSize: 9,
      fontFamily: "var(--fb)",
      fontWeight: 500,
      letterSpacing: "4px",
      textTransform: "uppercase",
      color,
      marginBottom: 10,
    }}>
      <div style={{ width: 24, height: 1, flexShrink: 0, backgroundColor: color }} />
      {children}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 style={{
      fontFamily: "'Fraunces', Georgia, serif",
      fontSize: 22,
      fontWeight: 300,
      color: "#0a1628",
      margin: "0 0 4px",
      lineHeight: 1.25,
    }}>
      {children}
    </h2>
  );
}

interface SectionProps {
  eyebrow: string;
  title?: string;
  description?: string;
  children: React.ReactNode;
}

function Section({ eyebrow, title, description, children }: SectionProps) {
  return (
    <section>
      <Eyebrow>{eyebrow}</Eyebrow>
      {title && <SectionTitle>{title}</SectionTitle>}
      {description && (
        <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)", margin: "0 0 16px", lineHeight: 1.7 }}>
          {description}
        </p>
      )}
      {children}
    </section>
  );
}

// Banner-variant KPI stat (used inside dark hero)
function HeroStat({ value, label, valueColor = "#E8C46A" }: { value: string; label: string; valueColor?: string }) {
  return (
    <div style={{ borderLeft: "2px solid #C8982A", paddingLeft: 18 }}>
      <div style={{
        fontFamily: "'Fraunces', Georgia, serif",
        fontSize: 34,
        fontWeight: 300,
        color: valueColor,
        lineHeight: 1,
        marginBottom: 8,
      }}>
        {value}
      </div>
      <div style={{ fontFamily: "var(--fb)", fontSize: 12, color: "rgba(255,255,255,0.5)", lineHeight: 1.55 }}>
        {label}
      </div>
    </div>
  );
}

function trustTierColor(score: number): string {
  if (score >= 70) return "var(--green)";
  if (score >= 40) return "var(--orange)";
  return "var(--red)";
}

// ── Component ────────────────────────────────────────────────────────────────

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
    setReport(prev =>
      prev ? {
        ...prev,
        trust_score:     pollData.trust_score,
        suspicion_index: pollData.suspicion_index,
        flagged:         pollData.flagged,
        flag_reason:     pollData.flag_reason,
        status:          pollData.status,
        signals:         pollData.signals,
      } : prev,
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

  // ── Grid texture (reused in hero) ────────────────────────────────────────
  const gridTexture = `
    linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px)
  `;

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>

      {/* ── HERO — full-bleed dark navy, no eyebrow ──────────────────── */}
      <section style={{
        backgroundColor: "var(--primary)",
        backgroundImage: gridTexture,
        backgroundSize: "48px 48px",
      }}>
        <div style={{
          maxWidth: 1600,
          margin: "0 auto",
          padding: "56px 80px",
          boxSizing: "border-box",
          display: "flex",
          alignItems: "center",
          gap: 80,
        }}>
          {/* Left: headline + stats */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {/* NO eyebrow in hero — BRAND.md §Page Structure Order rule */}
            <h1 style={{
              fontFamily: "'Fraunces', Georgia, serif",
              fontSize: "clamp(44px, 3.5vw, 72px)",
              fontWeight: 300,
              color: "#ffffff",
              margin: "0 0 20px",
              lineHeight: 1.15,
              maxWidth: 760,
            }}>
              Interview{" "}
              <em style={{ fontStyle: "italic", color: "var(--gold-light)" }}>Authenticity</em>
            </h1>
            <p style={{
              fontFamily: "var(--fb)",
              fontSize: "clamp(14px, 1vw, 16px)",
              color: "rgba(255,255,255,0.6)",
              lineHeight: 1.75,
              maxWidth: 600,
              margin: 0,
            }}>
              Five signal modules. One explainable TrustScore.
              Delivered within 60 s of call end.
            </p>

            {/* Demo badge */}
            {isDemo && (
              <div style={{
                display: "inline-flex",
                alignItems: "center",
                marginTop: 20,
                backgroundColor: "rgba(200,152,42,0.2)",
                border: "1px solid rgba(200,152,42,0.4)",
                borderRadius: 6,
                padding: "4px 12px",
                fontFamily: "var(--fb)",
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "2px",
                textTransform: "uppercase",
                color: "var(--gold-light)",
              }}>
                Demo Session
              </div>
            )}

            {/* Stat row — visible only when a session is loaded */}
            {displayData && (
              <div style={{ display: "flex", gap: 36, marginTop: 40, flexWrap: "wrap" }}>
                <HeroStat
                  value={displayData.trust_score.toFixed(1)}
                  label="TrustScore / 100"
                  valueColor={trustTierColor(displayData.trust_score)}
                />
                <HeroStat
                  value={`${(displayData.suspicion_index * 100).toFixed(1)}%`}
                  label="Suspicion Index"
                />
                <HeroStat
                  value={`#${displayData.session_id.slice(0, 8)}`}
                  label="Session ID"
                />
                <HeroStat
                  value={new Date(displayData.start_ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  label="Interview Date"
                />
              </div>
            )}
          </div>

          {/* Right: gauge — visible only when a session is loaded */}
          {displayData && (
            <div style={{ flexShrink: 0, width: 300 }}>
              <TrustScoreGauge trustScore={displayData.trust_score} />
            </div>
          )}
        </div>
      </section>

      {/* ── BODY — centered max-width container ──────────────────────── */}
      <div style={{
        maxWidth: 1600,
        margin: "0 auto",
        padding: "56px 80px",
        boxSizing: "border-box",
        width: "100%",
        display: "flex",
        gap: 48,
        alignItems: "flex-start",
      }}>

        {/* Sidebar — sticky so it doesn't scroll away */}
        <div style={{
          width: 300,
          flexShrink: 0,
          position: "sticky",
          top: 68,
          alignSelf: "flex-start",
        }}>
          <Sidebar
            recruiterId={recruiterId}
            sessionId={sessionId}
            polling={polling}
            loading={loading}
            onRecruiterIdChange={setRecruiterId}
            onSessionIdChange={setSessionId}
            onLoadSession={handleLoadSession}
            onLoadDemo={handleLoadDemo}
            onPollingToggle={() => setPolling(p => !p)}
          />
        </div>

        {/* Main content column */}
        <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 32 }}>

          {/* Error banner */}
          {error && (
            <div style={{
              backgroundColor: "var(--red-bg)",
              border: "1px solid var(--red)",
              borderLeft: "4px solid var(--red)",
              borderRadius: 8,
              padding: "12px 16px",
              fontFamily: "var(--fb)",
              fontSize: 13,
              color: "var(--red)",
              lineHeight: 1.6,
            }}>
              {error}
            </div>
          )}

          {/* Empty state */}
          {!displayData && !error && (
            <div style={{
              backgroundColor: "var(--white)",
              borderRadius: 14,
              boxShadow: "var(--shadow-md)",
              padding: "96px 64px",
              textAlign: "center",
              flex: 1,
            }}>
              <h2 style={{
                fontFamily: "'Fraunces', Georgia, serif",
                fontSize: 36,
                fontWeight: 300,
                color: "var(--primary)",
                margin: "0 0 20px",
                lineHeight: 1.25,
              }}>
                No session{" "}
                <em style={{ fontStyle: "italic", color: "var(--gold)" }}>loaded.</em>
              </h2>
              <p style={{ fontFamily: "var(--fb)", fontSize: 15, color: "var(--mid)", lineHeight: 1.8, maxWidth: 520, margin: "0 auto" }}>
                Enter a Recruiter ID and Session ID, then click <strong>Load Session</strong>
                — or click <strong>Load Demo</strong> to explore a synthetic flagged session.
              </p>
            </div>
          )}

          {/* ── Key Metrics ───────────────────────────────────────── */}
          {displayData && (
            <Section
              eyebrow="Key Metrics"
              description="Weighted aggregate across all five signal modules."
            >
              <KpiRow data={displayData} />
            </Section>
          )}

          {/* ── Signal Breakdown ──────────────────────────────────── */}
          {displayData && (
            <Section
              eyebrow="Signal Breakdown"
              description="Raw suspicion scores (coloured by tier) and weighted contributions per module."
            >
              <div style={{
                backgroundColor: "var(--white)",
                borderRadius: 12,
                boxShadow: "var(--shadow-card)",
                padding: "20px 24px",
              }}>
                <SignalBreakdownChart signals={displayData.signals} />
              </div>
            </Section>
          )}

          {/* ── Alert Panel (only when flagged) ──────────────────── */}
          {displayData && (
            <AlertPanel
              flagged={displayData.flagged}
              flagReason={displayData.flag_reason}
              signals={displayData.signals}
            />
          )}

          {/* ── Transcript ────────────────────────────────────────── */}
          {displayData && displayData.turns.length > 0 && (
            <Section
              eyebrow="Transcript"
              description="Per-turn suspicion heat map — candidate turns coloured by suspicion score."
            >
              <TranscriptView
                turns={displayData.turns as Array<{ speaker: string; text: string; suspicion_score?: number }>}
              />
            </Section>
          )}

          {/* ── PDF download (hidden in demo mode) ───────────────── */}
          {displayData && !isDemo && (
            <div>
              <button
                onClick={handleDownloadPdf}
                disabled={pdfBtnDisabled}
                style={{
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
                }}
              >
                ↓ Download PDF Report
              </button>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
