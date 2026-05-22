/**
 * Per-turn transcript with suspicion heat colouring.
 *
 * Each row background: rgba(224, 52, 72, opacity) where opacity = suspicion_score × 0.35.
 * Speaker label in Plus Jakarta Sans 600; RECRUITER in primary blue, CANDIDATE in dark.
 */

interface Turn {
  speaker: string;
  text: string;
  suspicion_score?: number;
}

interface Props {
  turns: Turn[];
}

export function TranscriptView({ turns }: Props) {
  if (turns.length === 0) {
    return (
      <div style={{ fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)", padding: "16px 0" }}>
        No transcript turns recorded for this session.
      </div>
    );
  }

  const container: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: 2,
    borderRadius: 12,
    overflow: "hidden",
    border: "1px solid var(--primary-10)",
  };

  return (
    <div style={container}>
      {turns.map((turn, i) => {
        const susp = turn.suspicion_score ?? 0;
        const heatOpacity = susp * 0.35;
        const isCandidate = turn.speaker.toUpperCase() === "CANDIDATE";

        const row: React.CSSProperties = {
          display: "flex",
          gap: 16,
          padding: "10px 16px",
          backgroundColor: `rgba(224, 52, 72, ${heatOpacity})`,
          borderBottom: i < turns.length - 1 ? "1px solid var(--primary-10)" : "none",
          alignItems: "flex-start",
        };

        const speakerStyle: React.CSSProperties = {
          fontFamily: "var(--fb)",
          fontSize: 9,
          fontWeight: 600,
          letterSpacing: "2px",
          textTransform: "uppercase",
          flexShrink: 0,
          width: 84,
          paddingTop: 2,
          color: isCandidate ? "var(--dark)" : "var(--primary-60)",
        };

        const textStyle: React.CSSProperties = {
          fontFamily: "var(--fb)",
          fontSize: 13,
          color: "var(--dark)",
          lineHeight: 1.65,
          flex: 1,
        };

        const suspBadge: React.CSSProperties = {
          flexShrink: 0,
          fontFamily: "var(--fb)",
          fontSize: 8,
          fontWeight: 600,
          color: susp >= 0.65 ? "var(--red)" : susp >= 0.35 ? "var(--orange)" : "var(--mid)",
          paddingTop: 2,
          letterSpacing: "0.5px",
        };

        return (
          <div key={i} style={row}>
            <span style={speakerStyle}>{turn.speaker}</span>
            <span style={textStyle}>{turn.text}</span>
            {turn.suspicion_score !== undefined && (
              <span style={suspBadge}>{susp.toFixed(2)}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
