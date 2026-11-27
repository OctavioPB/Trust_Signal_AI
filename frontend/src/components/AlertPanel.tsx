/**
 * AlertPanel — flagged-session callout.
 *
 * Renders nothing when flagged=false (use the SessionPage to render a
 * "cleared" callout where appropriate; this component is the *alert* form).
 *
 * Layout: red left-border card with the flag_reason and the top three
 * contributing signals listed with their weighted contributions.
 *
 * Review footer: a human confirms or clears the flag. That verdict is the only
 * training label the nightly DAG uses — the system never learns from its own flags.
 * The footer renders only when `onReview` is passed.
 */

import type { ReviewVerdict, SignalDetail } from "../types";

interface Props {
  flagged: boolean;
  flagReason: string;
  signals: SignalDetail[];
  reviewVerdict?: ReviewVerdict | null;
  onReview?: (verdict: ReviewVerdict) => void;
  reviewBusy?: boolean;
  reviewError?: string | null;
  reviewNote?: string;
}

const VERDICT_LABEL: Record<ReviewVerdict, string> = {
  confirmed: "AI assistance confirmed",
  cleared:   "Flag cleared as a false positive",
};

function tierColor(raw: number): string {
  if (raw >= 0.65) return "var(--rojo)";
  if (raw >= 0.35) return "var(--naranja)";
  return            "var(--verde)";
}

export function AlertPanel({
  flagged, flagReason, signals,
  reviewVerdict = null, onReview, reviewBusy = false, reviewError = null, reviewNote,
}: Props) {
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

      {onReview && (
        <div className="review" aria-label="Human review">
          <div className="review-head">
            <span className="review-title">Human review</span>
            {reviewVerdict ? (
              <span className={"badge " + (reviewVerdict === "confirmed" ? "danger" : "success")}>
                <span className="dot" />
                {VERDICT_LABEL[reviewVerdict]}
              </span>
            ) : (
              <span className="review-hint">
                Your verdict trains the nightly models. Unreviewed flags are never used.
              </span>
            )}
          </div>
          <div className="review-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={reviewBusy}
              aria-pressed={reviewVerdict === "confirmed"}
              onClick={() => onReview("confirmed")}
            >
              Confirm AI assistance
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              disabled={reviewBusy}
              aria-pressed={reviewVerdict === "cleared"}
              onClick={() => onReview("cleared")}
            >
              Clear flag
            </button>
          </div>
          {reviewError && <p className="review-error" role="alert">{reviewError}</p>}
          {reviewNote && !reviewError && <p className="review-note">{reviewNote}</p>}
        </div>
      )}
    </div>
  );
}
