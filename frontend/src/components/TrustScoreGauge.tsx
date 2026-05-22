/**
 * SVG semicircular gauge for TrustScore (0–100).
 *
 * Layout: viewBox 0 0 220 130, centre (110, 115), radius 100.
 * Three background zone arcs: [0,35] red · [35,70] orange · [70,100] green.
 * Score arc fills from left using stroke-dashoffset (CSS-animatable).
 * Gold threshold tick at score=35 matches Python FLAG_THRESHOLD.
 */

interface Props {
  trustScore: number;
  animated?: boolean;
}

const CX = 110;
const CY = 115;
const R = 100;
const CIRC = Math.PI * R; // semicircle arc length ≈ 314.16

/** Convert a TrustScore fraction (0–1) to a point on the arc. */
function arcPoint(frac: number): { x: number; y: number } {
  const rad = ((1 - frac) * 180 * Math.PI) / 180; // 0→left(π), 1→right(0)
  return { x: CX + R * Math.cos(rad), y: CY - R * Math.sin(rad) };
}

const P0   = { x: CX - R, y: CY };      // score=0   left  (10, 115)
const P35  = arcPoint(0.35);             // score=35  threshold
const P70  = arcPoint(0.70);             // score=70  upper boundary
const P100 = { x: CX + R, y: CY };      // score=100 right (210, 115)
const PTOP = { x: CX, y: CY - R };      // top of circle  (110, 15)

function arc(from: { x: number; y: number }, to: { x: number; y: number }): string {
  return `M ${from.x.toFixed(2)} ${from.y.toFixed(2)} A ${R} ${R} 0 0 0 ${to.x.toFixed(2)} ${to.y.toFixed(2)}`;
}

// Full semicircle split at top to avoid 180° arc ambiguity
const FULL_ARC = [
  `M ${P0.x} ${P0.y}`,
  `A ${R} ${R} 0 0 0 ${PTOP.x} ${PTOP.y}`,
  `A ${R} ${R} 0 0 0 ${P100.x} ${P100.y}`,
].join(" ");

function tierColor(score: number): string {
  if (score >= 70) return "var(--green)";
  if (score >= 40) return "var(--orange)";
  return "var(--red)";
}

function tierLabel(score: number): string {
  if (score >= 70) return "TRUSTWORTHY";
  if (score >= 40) return "MODERATE RISK";
  return "HIGH RISK";
}

export function TrustScoreGauge({ trustScore, animated = true }: Props) {
  const score = Math.max(0, Math.min(100, trustScore));
  const dashOffset = CIRC * (1 - score / 100);
  const color = tierColor(score);

  // Threshold tick at score=35 (inner and outer radial points)
  const threshAngleRad = ((1 - 0.35) * 180 * Math.PI) / 180;
  const tickOuter = { x: CX + R * Math.cos(threshAngleRad), y: CY - R * Math.sin(threshAngleRad) };
  const tickInner = { x: CX + (R - 18) * Math.cos(threshAngleRad), y: CY - (R - 18) * Math.sin(threshAngleRad) };

  const trackW = 14;

  return (
    <svg
      viewBox="0 0 220 130"
      width="100%"
      style={{ maxWidth: 320, display: "block", margin: "0 auto" }}
      aria-label={`TrustScore ${score.toFixed(1)} out of 100`}
    >
      {/* ── Background zone arcs (dimmed) ─────────────────────────── */}
      <path d={arc(P0, P35)} fill="none" stroke="var(--red)"    strokeWidth={trackW} strokeLinecap="butt" opacity={0.18} />
      <path d={arc(P35, P70)} fill="none" stroke="var(--orange)" strokeWidth={trackW} strokeLinecap="butt" opacity={0.18} />
      <path d={arc(P70, P100)} fill="none" stroke="var(--green)"  strokeWidth={trackW} strokeLinecap="butt" opacity={0.18} />

      {/* ── Score arc (animated fill via stroke-dashoffset) ────────── */}
      <path
        d={FULL_ARC}
        fill="none"
        stroke={color}
        strokeWidth={trackW}
        strokeLinecap="butt"
        strokeDasharray={`${CIRC} ${CIRC}`}
        strokeDashoffset={dashOffset}
        style={animated ? { transition: "stroke-dashoffset 0.65s ease-in-out, stroke 0.3s" } : undefined}
      />

      {/* ── Gold threshold line at score=35 ────────────────────────── */}
      <line
        x1={tickInner.x.toFixed(2)}
        y1={tickInner.y.toFixed(2)}
        x2={tickOuter.x.toFixed(2)}
        y2={tickOuter.y.toFixed(2)}
        stroke="var(--gold)"
        strokeWidth={2.5}
        strokeLinecap="round"
      />
      {/* Tiny gold label above the tick */}
      <text
        x={(tickOuter.x - 6).toFixed(2)}
        y={(tickOuter.y - 4).toFixed(2)}
        fill="var(--gold)"
        fontSize={7}
        fontFamily="var(--fb)"
        fontWeight={600}
        textAnchor="middle"
      >
        35
      </text>

      {/* ── Score text ─────────────────────────────────────────────── */}
      <text
        x={CX}
        y={96}
        textAnchor="middle"
        fill="var(--mid)"
        fontSize={8}
        fontFamily="var(--fb)"
        fontWeight={500}
        letterSpacing={2.5}
      >
        TRUSTSCORE
      </text>

      <text
        x={CX}
        y={113}
        textAnchor="middle"
        fill={color}
        fontSize={38}
        fontFamily="Fraunces, Georgia, serif"
        fontWeight={300}
        style={animated ? { transition: "fill 0.3s" } : undefined}
      >
        {score.toFixed(1)}
      </text>

      <text
        x={CX}
        y={126}
        textAnchor="middle"
        fill="var(--mid)"
        fontSize={8}
        fontFamily="var(--fb)"
        fontWeight={500}
        letterSpacing={1.5}
      >
        {tierLabel(score)}
      </text>
    </svg>
  );
}
