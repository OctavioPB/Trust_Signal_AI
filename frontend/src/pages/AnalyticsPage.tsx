/**
 * Analytics — aggregate session intelligence dashboard.
 *
 * Data: synthetic mock constants (replace with /api/analytics calls).
 * Charts: pure SVG. All SVG fill/stroke use raw hex per UI_Decisions §5 —
 * CSS custom properties do not apply to SVG presentation attributes.
 * Categorical series use the navy gradient; semantic colors (cleared/flagged
 * risk tiers) use their defined hex values.
 * KPI accent bars are always gold (CSS default) — never overridden.
 */

import { Eyebrow } from "../components/Eyebrow";

// ── Types ─────────────────────────────────────────────────────────────────────

interface WeekRow    { week: string; cleared: number; flagged: number; }
interface DistBucket { range: string; low: number; count: number; }
interface SigRate    { name: string; rate: number; count: number; }
interface FlagRow    { id: string; score: number; recruiter: string; date: string; reason: string; }

// ── Mock data ─────────────────────────────────────────────────────────────────

const TOTAL     = 218;
const FLAGGED_N = 31;
const AVG_SCORE = 71.4;
const DELTA_WK  = 12;

const DIST: DistBucket[] = [
  { range: "0–10",   low:  0, count:  3 },
  { range: "10–20",  low: 10, count:  7 },
  { range: "20–30",  low: 20, count:  8 },
  { range: "30–40",  low: 30, count: 13 },
  { range: "40–50",  low: 40, count: 19 },
  { range: "50–60",  low: 50, count: 28 },
  { range: "60–70",  low: 60, count: 41 },
  { range: "70–80",  low: 70, count: 52 },
  { range: "80–90",  low: 80, count: 34 },
  { range: "90–100", low: 90, count: 13 },
];

const WEEKLY: WeekRow[] = [
  { week: "Mar 24", cleared: 18, flagged: 3 },
  { week: "Mar 31", cleared: 21, flagged: 4 },
  { week: "Apr 7",  cleared: 24, flagged: 2 },
  { week: "Apr 14", cleared: 27, flagged: 5 },
  { week: "Apr 21", cleared: 22, flagged: 4 },
  { week: "Apr 28", cleared: 30, flagged: 3 },
  { week: "May 5",  cleared: 26, flagged: 6 },
  { week: "May 12", cleared: 29, flagged: 4 },
];

const SIGNALS: SigRate[] = [
  { name: "Semantic Similarity", rate: 0.68, count: 148 },
  { name: "Perplexity",          rate: 0.54, count: 118 },
  { name: "Response Latency",    rate: 0.41, count:  89 },
  { name: "Burstiness",          rate: 0.29, count:  63 },
  { name: "Background Audio",    rate: 0.17, count:  37 },
];

const RECENT_FLAGGED: FlagRow[] = [
  { id: "a1b2c3d4", score: 22.1, recruiter: "R-001", date: "May 21", reason: "High semantic similarity + low perplexity" },
  { id: "e5f6a7b8", score: 31.5, recruiter: "R-002", date: "May 21", reason: "Constant response latency pattern" },
  { id: "c9d0e1f2", score: 18.9, recruiter: "R-001", date: "May 20", reason: "Background keystroke audio during pauses" },
  { id: "a3b4c5d6", score: 28.3, recruiter: "R-003", date: "May 19", reason: "Perplexity below threshold on 7/12 turns" },
  { id: "e7f8a9b0", score: 35.7, recruiter: "R-002", date: "May 19", reason: "Burstiness variance below human baseline" },
];

// Risk-tier slices — semantic (red=danger, orange=moderate, green=clear).
// Uses hex because these are SVG stroke values (CSS vars don't apply in SVG attributes).
const TIER_SLICES = [
  { label: "Trustworthy",   pct: 51, color: "#27b97c" },
  { label: "Moderate Risk", pct: 31, color: "#f07020" },
  { label: "High Risk",     pct: 18, color: "#e03448" },
];

// Categorical signal series — navy gradient per UI_Decisions §5.
// Status colors (green/orange/red/purple) are reserved for semantic meaning only.
const SIG_COLORS = [
  "#003366",  // primary navy
  "#1a4d80",  // navy 80%
  "#336699",  // navy 60%
  "#4d7099",  // navy muted
  "#99bbdd",  // navy 30%
];

// ── Helpers ───────────────────────────────────────────────────────────────────

// Returns hex values — used as SVG fill, not CSS var() (which doesn't apply in SVG attrs).
function tierHex(score: number): string {
  if (score >= 70) return "#27b97c";
  if (score >= 40) return "#f07020";
  return "#e03448";
}

function tierColor(score: number): string {
  if (score >= 70) return "var(--verde)";
  if (score >= 40) return "var(--naranja)";
  return "var(--rojo)";
}

const CARD_LABEL: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: "2.5px",
  textTransform: "uppercase",
  fontWeight: 600,
  color: "var(--mid)",
  fontFamily: "var(--fb)",
  marginBottom: 20,
};

// ── Chart: TrustScore distribution histogram ──────────────────────────────────

function DistributionChart() {
  const max = Math.max(...DIST.map(d => d.count));
  const W = 500, H = 180, pb = 36, pt = 16, ph = 8;
  const availH = H - pt - pb;
  const barW   = (W - ph * 2) / DIST.length;
  const gap    = 4;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      aria-label="TrustScore distribution histogram"
      style={{ display: "block", overflow: "visible" }}
    >
      <line x1={ph} y1={H - pb} x2={W - ph} y2={H - pb} stroke="#e0eaf4" strokeWidth={1} />
      {DIST.map((d, i) => {
        const bH    = (d.count / max) * availH;
        const x     = ph + i * barW + gap / 2;
        const y     = H - pb - bH;
        const color = tierHex(d.low + 5);
        return (
          <g key={d.range}>
            <rect x={x} y={y} width={barW - gap} height={bH} fill={color} opacity={0.82} rx={2} />
            <text x={x + (barW - gap) / 2} y={y - 4}
              textAnchor="middle" fontSize={9} fontFamily="var(--fm)" fill="#6b7280">
              {d.count}
            </text>
            <text x={x + (barW - gap) / 2} y={H - pb + 14}
              textAnchor="middle" fontSize={8} fontFamily="var(--fb)" fill="#6b7280">
              {d.range}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ── Chart: weekly sessions grouped bar chart ──────────────────────────────────

function WeeklyBarChart() {
  const max    = Math.max(...WEEKLY.map(d => d.cleared + d.flagged));
  const W = 620, H = 200, pb = 36, pt = 24, ph = 8;
  const availH = H - pt - pb;
  const groupW = (W - ph * 2) / WEEKLY.length;
  const bW     = (groupW - 12) / 2;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      aria-label="Weekly sessions bar chart"
      style={{ display: "block", overflow: "visible" }}
    >
      {[0.25, 0.5, 0.75].map(f => (
        <line key={f}
          x1={ph} y1={H - pb - f * availH}
          x2={W - ph} y2={H - pb - f * availH}
          stroke="#e0eaf4" strokeWidth={1} strokeDasharray="4 3"
        />
      ))}
      <line x1={ph} y1={H - pb} x2={W - ph} y2={H - pb} stroke="#e0eaf4" strokeWidth={1} />

      {WEEKLY.map((d, i) => {
        const cH = (d.cleared / max) * availH;
        const fH = (d.flagged / max) * availH;
        const gx = ph + i * groupW + 6;
        return (
          <g key={d.week}>
            <rect x={gx}          y={H - pb - cH} width={bW} height={cH} fill="#27b97c" opacity={0.8} rx={2} />
            <rect x={gx + bW + 2} y={H - pb - fH} width={bW} height={fH} fill="#e03448" opacity={0.8} rx={2} />
            <text x={gx + bW} y={H - pb + 14} textAnchor="middle" fontSize={9} fontFamily="var(--fb)" fill="#6b7280">
              {d.week}
            </text>
          </g>
        );
      })}

      <circle cx={ph + 6}  cy={10} r={4} fill="#27b97c" opacity={0.8} />
      <text x={ph + 14} y={14} fontSize={9} fontFamily="var(--fb)" fill="#6b7280">Cleared</text>
      <circle cx={ph + 68} cy={10} r={4} fill="#e03448" opacity={0.8} />
      <text x={ph + 76} y={14} fontSize={9} fontFamily="var(--fb)" fill="#6b7280">Flagged</text>
    </svg>
  );
}

// ── Chart: risk tier donut ────────────────────────────────────────────────────

function TierDonut() {
  const r = 60, cx = 74, cy = 74;
  const circ = 2 * Math.PI * r;
  let cum = 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
      <svg viewBox="0 0 148 148" width={148} height={148} aria-label="Risk tier distribution">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#e0eaf4" strokeWidth={16} />
        {TIER_SLICES.map((t, i) => {
          const frac   = t.pct / 100;
          const dash   = frac * circ;
          const offset = cum * circ;
          cum += frac;
          return (
            <circle key={i} cx={cx} cy={cy} r={r}
              fill="none" stroke={t.color} strokeWidth={16}
              strokeDasharray={`${dash} ${circ - dash}`}
              strokeDashoffset={-offset}
              transform={`rotate(-90 ${cx} ${cy})`}
            />
          );
        })}
        <text x={cx} y={cy - 4} textAnchor="middle"
          fontFamily="Fraunces, Georgia, serif" fontSize={26} fontWeight={300} fill="#003366">
          {TOTAL}
        </text>
        <text x={cx} y={cy + 13} textAnchor="middle"
          fontFamily="var(--fb)" fontSize={7} letterSpacing={2} fill="#6b7280">
          SESSIONS
        </text>
      </svg>

      <div style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%" }}>
        {TIER_SLICES.map(t => (
          <div key={t.label} style={{ display: "grid", gridTemplateColumns: "12px 1fr auto", gap: 10, alignItems: "center" }}>
            <span style={{ width: 12, height: 12, borderRadius: 3, background: t.color, display: "inline-block" }} />
            <span style={{ fontSize: 12, color: "var(--dark)", fontFamily: "var(--fb)" }}>{t.label}</span>
            <span style={{ fontSize: 11, color: "var(--mid)", fontFamily: "var(--fm)" }}>{t.pct}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Signal trigger frequency bars ─────────────────────────────────────────────

function SignalTriggers() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {SIGNALS.map((s, i) => (
        <div key={s.name}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 7 }}>
            <span style={{ fontSize: 13, fontFamily: "var(--fb)", fontWeight: 600, color: "var(--dark)" }}>
              {s.name}
            </span>
            <span style={{ fontSize: 11, fontFamily: "var(--fm)", color: "var(--mid)" }}>
              {s.count} · {(s.rate * 100).toFixed(0)}%
            </span>
          </div>
          <div style={{ height: 8, background: "var(--primary-10)", borderRadius: 4, overflow: "hidden" }}>
            <div style={{
              height: "100%",
              width: `${s.rate * 100}%`,
              background: SIG_COLORS[i % SIG_COLORS.length],
              borderRadius: 4,
              transition: "width 0.5s ease",
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Recent flagged sessions table ─────────────────────────────────────────────

function FlaggedTable() {
  const TH: React.CSSProperties = {
    textAlign: "left",
    padding: "8px 12px",
    fontSize: 9,
    letterSpacing: "2.5px",
    textTransform: "uppercase",
    fontWeight: 600,
    color: "var(--mid)",
    fontFamily: "var(--fb)",
    borderBottom: "1px solid var(--border)",
    whiteSpace: "nowrap",
  };
  const TD: React.CSSProperties = { padding: "10px 12px", fontSize: 12, fontFamily: "var(--fb)" };

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={TH}>Session</th>
            <th style={TH}>Score</th>
            <th style={TH}>Recruiter</th>
            <th style={TH}>Date</th>
            <th style={TH}>Reason</th>
          </tr>
        </thead>
        <tbody>
          {RECENT_FLAGGED.map((row, i) => (
            <tr key={row.id} style={{ background: i % 2 === 0 ? "transparent" : "var(--light)" }}>
              <td style={{ ...TD, fontFamily: "var(--fm)", color: "var(--primary-60)", fontSize: 11 }}>
                #{row.id}
              </td>
              <td style={TD}>
                <span style={{
                  fontFamily: "Fraunces, Georgia, serif",
                  fontSize: 18,
                  fontWeight: 300,
                  color: tierColor(row.score),
                }}>
                  {row.score.toFixed(1)}
                </span>
              </td>
              <td style={{ ...TD, color: "var(--mid)" }}>{row.recruiter}</td>
              <td style={{ ...TD, color: "var(--mid)", whiteSpace: "nowrap" }}>{row.date}</td>
              <td style={{ ...TD, color: "var(--dark)", lineHeight: 1.55 }}>{row.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function AnalyticsPage() {
  const flaggedPct = ((FLAGGED_N / TOTAL) * 100).toFixed(1);
  const reportDate = new Date().toLocaleDateString("en-US", {
    year: "numeric", month: "long", day: "numeric",
  });

  return (
    <div className="analytics-page" style={{
      flex: 1,
      padding: "40px 56px 80px",
      boxSizing: "border-box",
      width: "100%",
      maxWidth: 1440,
      margin: "0 auto",
    }}>

      {/* ── Print-only executive header (hidden on screen) ──────────────── */}
      <div className="print-only print-report-header">
        <div className="print-brand">TrustSignal <em>AI</em></div>
        <div className="print-title">Executive Analytics Report</div>
        <div className="print-meta">
          <span>Generated: {reportDate}</span>
          <span>Confidential · Do Not Distribute</span>
        </div>
        <hr className="print-rule" />
      </div>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="section-head" style={{ marginBottom: 32 }}>
        <div className="titles">
          <Eyebrow>Analytics</Eyebrow>
          <h2>Session <em>intelligence</em></h2>
          <p className="lead">
            Aggregate trends across all recruiter sessions — risk distribution,
            signal frequency, and score evolution across the last 8 weeks.
          </p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 12 }}>
          <span className="badge info"><span className="dot" />Synthetic data</span>
          <button className="btn btn-ghost no-print" onClick={() => window.print()}>
            ↓&nbsp;Export PDF
          </button>
        </div>
      </div>

      {/* ── KPI row — accent bars always gold (never overridden) ─────────── */}
      <div className="kpi-grid" style={{ marginBottom: 24 }}>
        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top"><div className="kpi-lbl">Total Sessions</div></div>
          <div className="kpi-val" style={{ color: "var(--primary)" }}>
            {TOTAL}<span className="unit">all time</span>
          </div>
          <div className="kpi-sub">
            <span className="delta up">+{DELTA_WK} this week</span>
          </div>
        </div>

        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top">
            <div className="kpi-lbl">Flagged Rate</div>
            <span className="badge danger"><span className="dot" />High risk</span>
          </div>
          <div className="kpi-val" style={{ color: "var(--rojo)" }}>
            {flaggedPct}<span className="unit">%</span>
          </div>
          <div className="kpi-sub">{FLAGGED_N} of {TOTAL} sessions flagged</div>
        </div>

        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top">
            <div className="kpi-lbl">Avg TrustScore</div>
            <span className="badge success"><span className="dot" />Trustworthy</span>
          </div>
          <div className="kpi-val" style={{ color: "var(--verde)" }}>
            {AVG_SCORE.toFixed(1)}<span className="unit">/ 100</span>
          </div>
          <div className="kpi-sub">Fleet-wide weighted mean</div>
        </div>

        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top"><div className="kpi-lbl">Avg Duration</div></div>
          <div className="kpi-val" style={{ color: "var(--primary-60)" }}>
            18<span className="unit">m 22s</span>
          </div>
          <div className="kpi-sub">Per completed session</div>
        </div>
      </div>

      {/* ── Distribution + Risk tier ─────────────────────────────────────── */}
      <div className="distribution-row" style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 20, marginBottom: 20 }}>
        <div className="card">
          <div style={CARD_LABEL}>TrustScore Distribution</div>
          <DistributionChart />
          <div style={{ display: "flex", gap: 20, marginTop: 14, flexWrap: "wrap" }}>
            {[
              { label: "High Risk (<40)",    color: "#e03448" },
              { label: "Moderate (40–70)",   color: "#f07020" },
              { label: "Trustworthy (>70)",  color: "#27b97c" },
            ].map(({ label, color }) => (
              <span key={label} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, fontFamily: "var(--fb)", color: "var(--mid)", letterSpacing: "1px", textTransform: "uppercase" }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: color, display: "inline-block" }} />
                {label}
              </span>
            ))}
          </div>
        </div>
        <div className="card" style={{ minWidth: 220 }}>
          <div style={CARD_LABEL}>Risk Tier Split</div>
          <TierDonut />
        </div>
      </div>

      {/* ── Sessions over time ───────────────────────────────────────────── */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={CARD_LABEL}>Sessions Over Time · Last 8 Weeks</div>
        <WeeklyBarChart />
      </div>

      {/* ── Signal triggers + Flagged table ─────────────────────────────── */}
      <div className="signal-flagged-row" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <div className="card">
          <div style={CARD_LABEL}>Signal Trigger Frequency</div>
          <SignalTriggers />
        </div>
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <div style={CARD_LABEL}>Recent Flagged Sessions</div>
            <span className="badge danger"><span className="dot" />{FLAGGED_N} total</span>
          </div>
          <FlaggedTable />
        </div>
      </div>

    </div>
  );
}
