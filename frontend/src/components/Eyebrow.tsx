/**
 * Eyebrow — small uppercase label with a leading hairline rule.
 *
 * Used everywhere a section starts. Gold by default; pass variant="dark" on
 * dark backgrounds so the rule + text use --gold-light for AA contrast.
 *
 * Per OPB system: section starters read like numbered chapter headings.
 *   <Eyebrow>01 · Key Metrics</Eyebrow>
 */

import type { ReactNode } from "react";

interface Props {
  children: ReactNode;
  variant?: "default" | "dark" | "muted";
}

export function Eyebrow({ children, variant = "default" }: Props) {
  const cls =
    "eyebrow" +
    (variant === "dark" ? " on-dark" : variant === "muted" ? " muted" : "");
  return <div className={cls}>{children}</div>;
}
