/**
 * Alert panel shown when a session is flagged.
 * Renders nothing when flagged=false.
 *
 * BRAND.md: left-bordered archNote card, red badge, gold accent.
 */

import type { SignalDetail } from "../types";

interface Props {
  flagged: boolean;
  flagReason: string;
  signals: SignalDetail[];
}

export function AlertPanel({ flagged, flagReason, signals }: Props) {
  if (!flagged) return null;

  const panel: React.CSSProperties = {
    backgroundColor: "var(--red-bg)",
    borderRadius: 12,
    borderLeft: "4px solid var(--red)",
    padding: "20px 24px",
    display: "flex",
    flexDirection: "column",
    gap: 12,
  };

  const header: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 10,
  };

  const badge: React.CSSProperties = {
    fontFamily: "var(--fb)",
    fontSize: 9,
    fontWeight: 700,
    letterSpacing: "2px",
    textTransform: "uppercase",
    color: "var(--white)",
    backgroundColor: "var(--red)",
    borderRadius: 4,
    padding: "3px 8px",
  };

  const title: React.CSSProperties = {
    fontFamily: "var(--fb)",
    fontSize: 13,
    fontWeight: 600,
    color: "var(--red)",
  };

  const reasonText: React.CSSProperties = {
    fontFamily: "var(--fb)",
    fontSize: 13,
    color: "var(--dark)",
    lineHeight: 1.7,
    whiteSpace: "pre-line",
  };

  const signalList: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    marginTop: 4,
  };

  return (
    <div style={panel} role="alert" aria-live="assertive">
      <div style={header}>
        <span style={badge}>FLAGGED</span>
        <span style={title}>Session Alert — AI Assistance Detected</span>
      </div>

      <p style={reasonText}>{flagReason}</p>

      <div style={{ height: 1, backgroundColor: "var(--red)", opacity: 0.15 }} />

      <div>
        <div style={{ fontFamily: "var(--fb)", fontSize: 9, fontWeight: 700, letterSpacing: "3px", textTransform: "uppercase", color: "var(--red)", marginBottom: 8 }}>
          Signal Explanations
        </div>
        <div style={signalList}>
          {signals.map(sig => (
            <div key={sig.signal_name} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
              <div style={{
                flexShrink: 0,
                marginTop: 3,
                width: 6,
                height: 6,
                borderRadius: "50%",
                backgroundColor: sig.raw_score >= 0.65 ? "var(--red)" : sig.raw_score >= 0.35 ? "var(--orange)" : "var(--green)",
              }} />
              <div>
                <span style={{ fontFamily: "var(--fb)", fontSize: 11, fontWeight: 700, color: "var(--dark)" }}>
                  {sig.signal_name}
                </span>
                <span style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--mid)", marginLeft: 8 }}>
                  {sig.explanation}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
