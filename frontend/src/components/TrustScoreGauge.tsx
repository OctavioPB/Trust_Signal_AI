/**
 * TrustScoreGauge — a speedometer-style 0..100 score visual.
 *
 * Composition (BRAND.md):
 *  • Three-zone arc (red / orange / green) at the top.
 *  • Only the *active* zone is rendered solid; the other two sit dimmed
 *    in the background so the eye lands on the candidate's tier.
 *  • Gold needle points to the current score.
 *  • Gold threshold tick + label sits at score=35 (matches Python
 *    FLAG_THRESHOLD).
 *  • Score number lives BELOW the arc, large Fraunces 300.
 *  • Tier badge sits below the SVG.
 */

interface Props {
  trustScore: number;
  size?: number;
  /** Set false to drop animation, e.g. for printing. */
  animated?: boolean;
}

const ZONE_THRESHOLDS = { high: 40, mid: 70 };
const FLAG_TICK = 0.35; // 35/100 — must match server FLAG_THRESHOLD

function tier(score: number) {
  if (score >= ZONE_THRESHOLDS.mid)  return { name: "Trustworthy",    key: "low",  color: "var(--verde)"   };
  if (score >= ZONE_THRESHOLDS.high) return { name: "Moderate Risk",  key: "mid",  color: "var(--naranja)" };
  return                              { name: "High Risk",            key: "high", color: "var(--rojo)"    };
}

export function TrustScoreGauge({ trustScore, size = 300, animated = true }: Props) {
  const clamped = Math.max(0, Math.min(100, trustScore));
  const t = tier(clamped);

  // Geometry
  const VB_W = 320;
  const VB_H = 230;
  const cx = 160;
  const cy = 150;
  const r  = 124;
  const trackW = 10;

  const angle = (frac: number) => Math.PI * (1 - frac);
  const pt = (frac: number, radius: number = r) => {
    const a = angle(frac);
    return { x: cx + radius * Math.cos(a), y: cy - radius * Math.sin(a) };
  };
  const arcPath = (from: { x: number; y: number }, to: { x: number; y: number }) =>
    `M ${from.x.toFixed(2)} ${from.y.toFixed(2)} A ${r} ${r} 0 0 1 ${to.x.toFixed(2)} ${to.y.toFixed(2)}`;

  const P0   = pt(0);
  const P40  = pt(0.40);
  const P70  = pt(0.70);
  const P100 = pt(1);

  // Needle triangle
  const needleFrac = clamped / 100;
  const tip   = pt(needleFrac, r - 8);
  const baseL = pt(needleFrac - 0.02, r + 8);
  const baseR = pt(needleFrac + 0.02, r + 8);
  const needlePath = `M ${baseL.x.toFixed(2)} ${baseL.y.toFixed(2)} L ${tip.x.toFixed(2)} ${tip.y.toFixed(2)} L ${baseR.x.toFixed(2)} ${baseR.y.toFixed(2)} Z`;

  // Threshold tick at 35
  const tkOuter = pt(FLAG_TICK, r + 10);
  const tkInner = pt(FLAG_TICK, r - 10);
  const tkLabel = pt(FLAG_TICK, r + 22);

  // Active zone (only one rendered solid)
  let activeFrom = P0, activeTo = P40, activeColor: string = "var(--rojo)";
  if (clamped >= ZONE_THRESHOLDS.mid)       { activeFrom = P70;  activeTo = P100; activeColor = "var(--verde)";   }
  else if (clamped >= ZONE_THRESHOLDS.high) { activeFrom = P40;  activeTo = P70;  activeColor = "var(--naranja)"; }

  const axisLabels: { frac: number; text: string }[] = [
    { frac: 0,    text: "0"   },
    { frac: 0.70, text: "70"  },
    { frac: 1,    text: "100" },
  ];

  const transition = animated
    ? "all 0.65s cubic-bezier(.4, 1.4, .5, 1), fill 0.3s"
    : undefined;

  return (
    <div className="gauge-wrap" style={{ width: size }}>
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        width={size}
        style={{ display: "block", overflow: "visible" }}
        aria-label={`TrustScore ${clamped.toFixed(1)} of 100`}
      >
        {/* Dimmed zone backgrounds */}
        <path d={arcPath(P0,  P40)}  fill="none" stroke="var(--rojo)"    strokeWidth={trackW} opacity={0.28} strokeLinecap="butt" />
        <path d={arcPath(P40, P70)}  fill="none" stroke="var(--naranja)" strokeWidth={trackW} opacity={0.28} strokeLinecap="butt" />
        <path d={arcPath(P70, P100)} fill="none" stroke="var(--verde)"   strokeWidth={trackW} opacity={0.28} strokeLinecap="butt" />

        {/* Active zone */}
        <path
          d={arcPath(activeFrom, activeTo)}
          fill="none"
          stroke={activeColor}
          strokeWidth={trackW}
          strokeLinecap="butt"
          style={animated ? { transition: "all 0.3s ease" } : undefined}
        />

        {/* Threshold tick @ 35 */}
        <line
          x1={tkInner.x.toFixed(2)} y1={tkInner.y.toFixed(2)}
          x2={tkOuter.x.toFixed(2)} y2={tkOuter.y.toFixed(2)}
          stroke="var(--gold-light)" strokeWidth={2} strokeLinecap="round"
        />
        <text
          x={tkLabel.x.toFixed(2)} y={tkLabel.y.toFixed(2)}
          fill="var(--gold-light)" fontSize={9.5}
          fontFamily="var(--fb)" fontWeight={700} letterSpacing={2}
          textAnchor="middle"
        >
          35 · FLAG
        </text>

        {/* Axis labels */}
        {axisLabels.map(({ frac, text }) => {
          const p = pt(frac, r + 20);
          return (
            <text
              key={text}
              x={p.x.toFixed(2)} y={p.y.toFixed(2)}
              fill="rgba(255,255,255,0.4)" fontSize={10}
              fontFamily="var(--fb)" fontWeight={600} letterSpacing={1.5}
              textAnchor="middle" dominantBaseline="hanging"
            >
              {text}
            </text>
          );
        })}

        {/* Needle */}
        <path d={needlePath} fill={t.color} style={transition ? { transition } : undefined} />
        <circle cx={cx} cy={cy} r={6} fill="#fff" opacity={0.9} />
        <circle cx={cx} cy={cy} r={3} fill={t.color} style={animated ? { transition: "fill 0.3s" } : undefined} />

        {/* Score number — below the arc */}
        <text
          x={cx} y={196}
          textAnchor="middle"
          fill={t.color}
          fontFamily="Fraunces, Georgia, serif"
          fontSize={56} fontWeight={300}
          style={animated ? { transition: "fill 0.3s" } : undefined}
        >
          {clamped.toFixed(1)}
          <tspan fontSize={18} fontFamily="var(--fb)" fontWeight={500} fill="rgba(255,255,255,0.4)" dx={6}>
            / 100
          </tspan>
        </text>

        {/* Caption */}
        <text
          x={cx} y={220}
          textAnchor="middle"
          fill="rgba(255,255,255,0.4)"
          fontSize={9.5} fontFamily="var(--fb)"
          fontWeight={600} letterSpacing={3.5}
        >
          TRUSTSCORE
        </text>
      </svg>

      <div className="gauge-tier" style={{ color: t.color }}>
        <span className="dot" />
        {t.name}
      </div>
    </div>
  );
}
