/**
 * AlertPanel — flagged-session callout.
 *
 * Renders nothing when flagged=false (use the SessionPage to render a
 * "cleared" callout where appropriate; this component is the *alert* form).
 *
 * Layout: red left-border card with the flag_reason and the top three
 * contributing signals listed with their weighted contributions.
 *
 * Drop-in — same props as the original.
 */

import type { SignalDetail } from "../types";

interface Props {
  flagged: boolean;
  flagReason: string;
  signals: SignalDetail[];
}

function tierColor(raw: number): string {
  if (raw >= 0.65) return "var(--rojo)";
  if (raw >= 0.35) return "var(--naranja)";
  return            "var(--verde)";
}

export function AlertPanel({ flagged, flagReason, signals }: Props) {
  if (!flagged) return null;

  const topThree = [...signals]
    .sort((a, b) => b.weighted_contribution - a.weighted_contribution)
    .slice(0, 3);

  return (
    <div className="alert" role="alert" aria-live="assertive">
      <div className="alert-head">
        <h3>
          AI-assistance signals <em>detected</em>
        </h3>
        <div style={{ display: "flex", gap: 8 }}>
          <span className="badge danger">
            <span className="dot" />
            Flagged
          </span>
        </div>
      </div>

      <p className="reason">{flagReason}</p>

      <div className="factors">
        <div
          style={{
            fontSize: 11,
            letterSpacing: 2.5,
            textTransform: "uppercase",
            fontWeight: 600,
            color: "var(--rojo-dark)",
          }}
        >
          Top contributing signals
        </div>
        {topThree.map((s) => (
          <div className="factor" key={s.signal_name}>
            <div className="dot" style={{ background: tierColor(s.raw_score) }} />
            <div className="text">
              <b>{s.signal_name}</b>
              {s.explanation}
            </div>
            <div className="v">+{s.weighted_contribution.toFixed(3)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
