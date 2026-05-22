/**
 * Horizontal SVG bar chart for the five TrustSignal signal modules.
 *
 * Each row shows two bars:
 *   • Raw score      (coloured by tier: ≥0.65 red · ≥0.35 orange · else green)
 *   • Weighted contribution (same colour, 60 % opacity)
 *
 * All geometry is pure SVG math — no transforms, no external libraries.
 */

import type { SignalDetail } from "../types";

interface Props {
  signals: SignalDetail[];
}

const ROW_H   = 44;
const PAD_TOP = 4;
const LABEL_W = 136;
const BAR_MAX = 210;  // px when score = 1.0
const BAR_GAP = 6;    // gap between label area and bar start
const VAL_GAP = 8;    // gap between bar end and value label

const SVG_W = LABEL_W + BAR_GAP + BAR_MAX + VAL_GAP + 36;
const RAW_H = 10;
const WGT_H = 7;

function tierColor(rawScore: number): string {
  if (rawScore >= 0.65) return "var(--red)";
  if (rawScore >= 0.35) return "var(--orange)";
  return "var(--green)";
}

function tierLabel(rawScore: number): string {
  if (rawScore >= 0.65) return "HIGH";
  if (rawScore >= 0.35) return "MED";
  return "LOW";
}

export function SignalBreakdownChart({ signals }: Props) {
  const svgH = PAD_TOP + signals.length * ROW_H + 4;

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${svgH}`}
      width="100%"
      style={{ display: "block", overflow: "visible" }}
      aria-label="Signal breakdown chart"
    >
      {signals.map((sig, i) => {
        const rowY    = PAD_TOP + i * ROW_H;
        const color   = tierColor(sig.raw_score);
        const barX    = LABEL_W + BAR_GAP;
        const rawW    = sig.raw_score * BAR_MAX;
        const wgtW    = sig.weighted_contribution * BAR_MAX;
        const valueX  = barX + BAR_MAX + VAL_GAP;
        const isEven  = i % 2 === 0;

        return (
          <g key={sig.signal_name}>
            {/* Row background */}
            <rect
              x={0}
              y={rowY}
              width={SVG_W}
              height={ROW_H - 2}
              fill={isEven ? "var(--primary-10)" : "var(--white)"}
              opacity={0.4}
              rx={4}
            />

            {/* Signal name */}
            <text
              x={4}
              y={rowY + 14}
              fill="var(--dark)"
              fontSize={11}
              fontFamily="var(--fb)"
              fontWeight={600}
            >
              {sig.signal_name}
            </text>

            {/* Track for raw score */}
            <rect x={barX} y={rowY + 8} width={BAR_MAX} height={RAW_H} rx={3} fill="var(--primary-10)" />

            {/* Raw score bar */}
            <rect
              x={barX}
              y={rowY + 8}
              width={rawW}
              height={RAW_H}
              rx={3}
              fill={color}
              style={{ transition: "width 0.5s ease-in-out" }}
            />

            {/* Track for weighted contribution */}
            <rect x={barX} y={rowY + 24} width={BAR_MAX} height={WGT_H} rx={2} fill="var(--primary-10)" />

            {/* Weighted contribution bar */}
            <rect
              x={barX}
              y={rowY + 24}
              width={wgtW}
              height={WGT_H}
              rx={2}
              fill={color}
              opacity={0.55}
              style={{ transition: "width 0.5s ease-in-out" }}
            />

            {/* Bar labels (right of track) */}
            <text
              x={valueX}
              y={rowY + 17}
              fill={color}
              fontSize={10}
              fontFamily="var(--fb)"
              fontWeight={600}
            >
              {sig.raw_score.toFixed(2)}
            </text>
            <text
              x={valueX}
              y={rowY + 31}
              fill="var(--mid)"
              fontSize={9}
              fontFamily="var(--fb)"
            >
              {sig.weighted_contribution.toFixed(3)}
            </text>

            {/* Tier chip */}
            <text
              x={LABEL_W - 2}
              y={rowY + 17}
              textAnchor="end"
              fill={color}
              fontSize={8}
              fontFamily="var(--fb)"
              fontWeight={700}
              letterSpacing={1}
            >
              {tierLabel(sig.raw_score)}
            </text>
          </g>
        );
      })}

      {/* Legend */}
      <g transform={`translate(${LABEL_W + BAR_GAP}, ${svgH - 1})`}>
        <rect x={0} y={-8} width={10} height={7} rx={2} fill="var(--dark)" opacity={0.4} />
        <text x={13} y={-2} fill="var(--mid)" fontSize={8} fontFamily="var(--fb)">raw score</text>
        <rect x={70} y={-8} width={10} height={7} rx={2} fill="var(--dark)" opacity={0.22} />
        <text x={83} y={-2} fill="var(--mid)" fontSize={8} fontFamily="var(--fb)">weighted contribution</text>
      </g>
    </svg>
  );
}
