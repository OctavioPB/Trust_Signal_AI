/**
 * KpiRow — the top-line stats grid.
 *
 * Four cards: TrustScore · Suspicion Index · Status · Turns analysed.
 * Each card carries a tier-coloured accent bar on the left and a tier
 * badge in the top-right.
 *
 * Drop-in for the original — same `data` prop shape.
 */

import type { ReactNode } from "react";
import type { ScoreResponse, ReportResponse } from "../types";

interface CardProps {
  label: string;
  value: ReactNode;
  unit?: string;
  sub?: ReactNode;
  valueColor?: string;  // accent bar is always gold (CSS); this controls value text only
  badge?: ReactNode;
}

function KpiCard({ label, value, unit, sub, valueColor = "var(--dark)", badge }: CardProps) {
  return (
    <div className="kpi">
      <span className="kpi-accent" />   {/* always gold via .kpi .kpi-accent CSS */}
      <div className="kpi-top">
        <div className="kpi-lbl">{label}</div>
        {badge}
      </div>
      <div className="kpi-val" style={{ color: valueColor }}>
        {value}
        {unit && <span className="unit">{unit}</span>}
      </div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

function tierForScore(score: number): { name: string; color: string; badgeCls: string } {
  if (score >= 70) return { name: "Trustworthy",   color: "var(--verde)",   badgeCls: "success" };
  if (score >= 40) return { name: "Moderate Risk", color: "var(--naranja)", badgeCls: "warning" };
  return            { name: "High Risk",           color: "var(--rojo)",    badgeCls: "danger"  };
}

function statusColor(status: string, flagged: boolean): string {
  if (flagged)            return "var(--rojo)";
  if (status === "live")  return "var(--naranja)";
  return                          "var(--verde)";
}

interface Props {
  data: Pick<ScoreResponse, "trust_score" | "suspicion_index" | "flagged" | "status">
      & Partial<Pick<ReportResponse, "turns" | "start_ts" | "end_ts">>;
}

function fmtDuration(start?: number, end?: number | null): string {
  if (start === undefined) return "—";
  const seconds = Math.max(0, (end ?? Math.floor(Date.now() / 1000)) - start);
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function KpiRow({ data }: Props) {
  const t      = tierForScore(data.trust_score);
  const susHi  = data.suspicion_index >= 0.65;
  const susMid = data.suspicion_index >= 0.35;
  const susTier   = susHi ? "danger" : susMid ? "warning" : "success";
  const susColor  = susHi ? "var(--rojo)" : susMid ? "var(--naranja)" : "var(--verde)";
  const statusFg  = statusColor(data.status, data.flagged);
  const statusBadgeTone = data.flagged ? "danger" : data.status === "live" ? "warning" : "success";

  return (
    <div className="kpi-grid">
      <KpiCard
        label="TrustScore"
        value={data.trust_score.toFixed(1)}
        unit="/ 100"
        sub={<span className="delta" style={{ color: t.color }}>{t.name}</span>}
        valueColor={t.color}
        badge={
          <span className={`badge ${t.badgeCls}`}>
            <span className="dot" />
            {t.name}
          </span>
        }
      />
      <KpiCard
        label="Suspicion Index"
        value={data.suspicion_index.toFixed(3)}
        sub={<>threshold <code style={{ fontFamily: "var(--fm)" }}>≥ 0.65</code></>}
        valueColor={susColor}
        badge={
          <span className={"badge " + susTier}>
            <span className="dot" />
            {susHi ? "Over" : "Under"}
          </span>
        }
      />
      <KpiCard
        label="Status"
        value={data.flagged ? "Flagged" : data.status === "live" ? "Live" : "Cleared"}
        sub={data.flagged ? "Review recommended" : "No action required"}
        valueColor={statusFg}
        badge={
          <span className={"badge " + statusBadgeTone}>
            <span className="dot" />
            {data.status.toUpperCase()}
          </span>
        }
      />
      <KpiCard
        label="Turns Analysed"
        value={data.turns ? data.turns.length : 0}
        sub={<>across {fmtDuration(data.start_ts, data.end_ts)}</>}
        valueColor="var(--primary-60)"
      />
    </div>
  );
}
