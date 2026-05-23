/**
 * TranscriptView — per-turn transcript with suspicion heat colouring.
 *
 * Heat is expressed by a coloured 4px bar on the LEFT of each turn (the
 * previous version flooded the whole row red, which fought the rest of the
 * dashboard). Saturation grows with suspicion_score.
 *
 * Drop-in — same `turns` prop shape as the original.
 */

interface Turn {
  speaker: string;
  text: string;
  suspicion_score?: number;
  /** Optional timestamp string like "00:42" — falls through when present. */
  t?: string;
}

interface Props {
  turns: Turn[];
}

function tierColor(sus: number): string {
  if (sus >= 0.65) return "var(--rojo)";
  if (sus >= 0.35) return "var(--naranja)";
  return            "var(--verde)";
}

export function TranscriptView({ turns }: Props) {
  if (turns.length === 0) {
    return (
      <div className="card" style={{ color: "var(--mid)", fontSize: 13 }}>
        No transcript turns recorded for this session.
      </div>
    );
  }

  return (
    <div className="transcript">
      <div className="transcript-head">
        <div className="legend">
          <span>Suspicion intensity</span>
          <div className="heat-bar">
            <span>0.0</span>
            <div className="grad" />
            <span>1.0</span>
          </div>
        </div>
        <span style={{ fontSize: 11, color: "var(--mid)", fontFamily: "var(--fm)" }}>
          {turns.length} turns · candidate-only scored
        </span>
      </div>

      {turns.map((turn, i) => {
        const sus = turn.suspicion_score ?? 0;
        const isCand = turn.speaker.toUpperCase() === "CANDIDATE";
        const color = tierColor(sus);
        const intensity = Math.min(1, sus * 1.2);
        return (
          <div key={i} className={"turn " + (isCand ? "candidate" : "recruiter")}>
            <div
              className="heat"
              style={{
                background: isCand ? color : "var(--primary-10)",
                opacity: isCand ? 0.35 + intensity * 0.65 : 0.4,
              }}
            />
            <div>
              <div className={"speaker " + (isCand ? "candidate" : "recruiter")}>
                {turn.speaker}
                {turn.t && <span className="timestamp">{turn.t}</span>}
              </div>
            </div>
            <div className="text">{turn.text}</div>
            {isCand && (
              <div className="susp" style={{ color }}>
                {sus.toFixed(2)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
