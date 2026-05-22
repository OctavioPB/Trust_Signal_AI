/**
 * Four KPI stat cards in a flex row.
 * Cards follow the BRAND.md "dashboard variant" with a left gold accent bar.
 */

import type { ScoreResponse } from "../types";

interface Props {
  data: Pick<ScoreResponse, "trust_score" | "suspicion_index" | "flagged" | "status">;
}

interface CardProps {
  label: string;
  value: React.ReactNode;
  sub?: string;
  accentColor?: string;
}

function Card({ label, value, sub, accentColor = "var(--gold)" }: CardProps) {
  const card: React.CSSProperties = {
    flex: 1,
    minWidth: 0,
    backgroundColor: "var(--white)",
    borderRadius: 12,
    boxShadow: "var(--shadow-card)",
    padding: "20px 20px 16px",
    display: "flex",
    gap: 14,
    alignItems: "stretch",
  };

  const accent: React.CSSProperties = {
    width: 3,
    borderRadius: 2,
    backgroundColor: accentColor,
    flexShrink: 0,
  };

  const body: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: 4,
    minWidth: 0,
  };

  return (
    <div style={card}>
      <div style={accent} />
      <div style={body}>
        <div style={{ fontFamily: "var(--fb)", fontSize: 10, letterSpacing: "3px", textTransform: "uppercase", color: "var(--mid)" }}>
          {label}
        </div>
        <div style={{ fontFamily: "Fraunces, Georgia, serif", fontSize: 32, fontWeight: 300, color: "var(--dark)", lineHeight: 1 }}>
          {value}
        </div>
        {sub && (
          <div style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--mid)" }}>
            {sub}
          </div>
        )}
      </div>
    </div>
  );
}

function flagColor(flagged: boolean): string {
  return flagged ? "var(--red)" : "var(--green)";
}

function statusColor(status: string): string {
  if (status === "flagged")   return "var(--red)";
  if (status === "completed") return "var(--green)";
  return "var(--gold)"; // live / unknown
}

export function KpiRow({ data }: Props) {
  const { trust_score, suspicion_index, flagged, status } = data;

  const scoreColor = trust_score >= 70 ? "var(--green)" : trust_score >= 40 ? "var(--orange)" : "var(--red)";

  const badge: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    borderRadius: 20,
    padding: "4px 12px",
    backgroundColor: flagged ? "var(--red-bg)" : "var(--green-bg)",
    fontFamily: "var(--fb)",
    fontSize: 10,
    fontWeight: 600,
    letterSpacing: "1px",
    color: flagColor(flagged),
  };

  const statusBadge: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    borderRadius: 20,
    padding: "4px 12px",
    backgroundColor: "var(--primary-10)",
    fontFamily: "var(--fb)",
    fontSize: 10,
    fontWeight: 600,
    letterSpacing: "1px",
    color: statusColor(status),
  };

  return (
    <div style={{ display: "flex", gap: "var(--gap-md)", flexWrap: "wrap" }}>
      <Card
        label="TrustScore"
        value={<span style={{ color: scoreColor }}>{trust_score.toFixed(1)}</span>}
        sub="out of 100"
        accentColor={scoreColor}
      />
      <Card
        label="Suspicion Index"
        value={suspicion_index.toFixed(4)}
        sub="threshold ≥ 0.65"
        accentColor={suspicion_index >= 0.65 ? "var(--red)" : "var(--gold)"}
      />
      <Card
        label="Flag Status"
        value={
          <div style={badge}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: flagColor(flagged), display: "inline-block" }} />
            {flagged ? "FLAGGED" : "CLEAR"}
          </div>
        }
        accentColor={flagColor(flagged)}
      />
      <Card
        label="Session Status"
        value={
          <div style={statusBadge}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: statusColor(status), display: "inline-block" }} />
            {status.toUpperCase()}
          </div>
        }
        accentColor={statusColor(status)}
      />
    </div>
  );
}
