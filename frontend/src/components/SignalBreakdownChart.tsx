/**
 * SignalBreakdownChart — five signal modules in a two-column layout.
 *
 * LEFT  — per-signal list: name, optional sub-label, raw bar, weighted bar,
 *         and a big tier number (0..100 raw-score percentile) on the right.
 * RIGHT — donut showing each signal's share of the *total weighted* suspicion,
 *         with the suspicion_index in the centre.
 *
 * Drop-in for the original — same `signals` prop. If you also pass
 * `suspicionIndex`, it goes in the donut centre; otherwise we compute the
 * raw weighted sum.
 */

import type { SignalDetail } from "../types";

interface Props {
  signals: SignalDetail[];
  suspicionIndex?: number;
}

function tierFromRaw(raw: number) {
  if (raw >= 0.65) return { name: "High", key: "high", color: "var(--rojo)",    fill: "fill-high" };
  if (raw >= 0.35) return { name: "Med",  key: "mid",  color: "var(--naranja)", fill: "fill-mid"  };
  return            { name: "Low",  key: "low",  color: "var(--verde)",   fill: "fill-low"  };
}

/** Optional human-readable sub-label per signal_name — purely cosmetic. */
const SIGNAL_SUBS: Record<string, string> = {
  "Response Latency":    "Pre-answer pause variance",
  "Background Audio":    "Keystroke & ambient detection",
  "Perplexity":          "Predictability of phrasing (GPT-2)",
  "Burstiness":          "Sentence-length variance",
  "Semantic Similarity": "Match vs. canonical LLM answer bank",
};

function SignalRow({ sig, idx }: { sig: SignalDetail; idx: number }) {
  const t = tierFromRaw(sig.raw_score);
  const sub = SIGNAL_SUBS[sig.signal_name];
  return (
    <div className="signal-row">
      <div className="sig-idx">{String(idx + 1).padStart(2, "0")}</div>
      <div className="sig-name">
        {sig.signal_name}
        {sub && <span className="sig-sub">{sub}</span>}
      </div>
      <div className="sig-bars">
        <div className="sig-bar-row">
          <span>Raw</span>
          <div className="track">
            <div className={"fill " + t.fill} style={{ width: `${sig.raw_score * 100}%` }} />
          </div>
          <span className="val">{sig.raw_score.toFixed(2)}</span>
        </div>
        <div className="sig-bar-row weight">
          <span>Weighted</span>
          <div className="track">
            <div
              className={"fill " + t.fill}
              style={{ width: `${sig.weighted_contribution * 100}%`, opacity: 0.55 }}
            />
          </div>
          <span className="val">{sig.weighted_contribution.toFixed(3)}</span>
        </div>
      </div>
      <div className="sig-tier">
        <div className="pct" style={{ color: t.color }}>{Math.round(sig.raw_score * 100)}</div>
        <div className={"lbl tier-" + t.key}>{t.name}</div>
      </div>
    </div>
  );
}

// Per-signal series colours for the donut — navy gradient per UI_Decisions §5.
// SVG fill/stroke must use raw hex (CSS custom properties do not apply in SVG attributes).
const DONUT_PALETTE = [
  "#003366",  // primary navy
  "#1a4d80",  // navy 80%
  "#336699",  // navy 60%
  "#4d7099",  // navy muted
  "#99bbdd",  // navy 30%
];

function ContributionDonut({
  signals,
  suspicionIndex,
}: {
  signals: SignalDetail[];
  suspicionIndex: number;
}) {
  const total = signals.reduce((acc, s) => acc + s.weighted_contribution, 0);

  const r = 64;
  const cx = 78;
  const cy = 78;
  const circ = 2 * Math.PI * r;

  let cumFrac = 0;
  const arcs = signals.map((s, i) => {
    const frac = total > 0 ? s.weighted_contribution / total : 0;
    const dash = frac * circ;
    const offset = cumFrac * circ;
    cumFrac += frac;
    return { color: DONUT_PALETTE[i % DONUT_PALETTE.length], dash, offset, sig: s, frac };
  });

  return (
    <div className="card">
      <div className="donut-wrap">
        <div className="donut-title">Contribution Mix</div>
        <svg viewBox="0 0 156 156" width={156} height={156} aria-label="Signal contribution donut">
          <circle cx={cx} cy={cy} r={r} fill="none" stroke="#e0eaf4" strokeWidth={18} />
          {arcs.map((a, i) => (
            <circle
              key={i}
              cx={cx} cy={cy} r={r}
              fill="none"
              stroke={a.color}
              strokeWidth={18}
              strokeDasharray={`${a.dash} ${circ - a.dash}`}
              strokeDashoffset={-a.offset}
              transform={`rotate(-90 ${cx} ${cy})`}
              style={{ transition: "stroke-dasharray 0.5s ease" }}
            />
          ))}
          <text
            x={cx} y={cy - 4} textAnchor="middle"
            fontFamily="Fraunces, Georgia, serif"
            fontSize={28} fontWeight={300} fill="#003366"
          >
            {(suspicionIndex * 100).toFixed(1)}
          </text>
          <text
            x={cx} y={cy + 14} textAnchor="middle"
            fontFamily="var(--fb)" fontSize={9}
            letterSpacing={2.5} fontWeight={600} fill="#6b7280"
          >
            SUSPICION
          </text>
        </svg>
        <div className="donut-legend">
          {arcs.map((a, i) => (
            <div className="leg" key={i}>
              <span className="swatch" style={{ background: a.color }} />
              <span>{a.sig.signal_name}</span>
              <span className="v">{(a.frac * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function SignalBreakdownChart({ signals, suspicionIndex }: Props) {
  const total = signals.reduce((acc, s) => acc + s.weighted_contribution, 0);
  const si = suspicionIndex ?? total;

  return (
    <div className="signals-grid">
      <div className="card">
        <div className="signal-list">
          {signals.map((s, i) => (
            <SignalRow key={s.signal_name} sig={s} idx={i} />
          ))}
        </div>
      </div>
      <ContributionDonut signals={signals} suspicionIndex={si} />
    </div>
  );
}
