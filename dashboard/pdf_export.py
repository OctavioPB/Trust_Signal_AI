"""PDF report generation for TrustSignal AI.

Generates a formatted A4 PDF from a ReportResponse dict using fpdf2.
The PDF is returned as bytes so it can be offered as a Streamlit download.

Layout:
  - Dark navy header bar with title
  - Session metadata block (IDs, timestamps, status)
  - TrustScore callout (color-coded)
  - Flag alert block (when flagged=True)
  - Signal breakdown table
  - Per-signal explanation text
  - Footer with generation timestamp
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fpdf import FPDF

# ── Color constants (from BRAND.md) ───────────────────────────────────────────

_C_PRIMARY   = (0,   51,  102)   # #003366
_C_PRIMARY10 = (224, 234, 244)   # #E0EAF4
_C_GOLD      = (200, 152, 42)    # #C8982A
_C_DARK      = (28,  28,  46)    # #1C1C2E
_C_MID       = (107, 114, 128)   # #6B7280
_C_WHITE     = (255, 255, 255)
_C_GREEN     = (39,  185, 124)   # #27B97C
_C_GREEN_BG  = (224, 247, 239)   # #E0F7EF
_C_ORANGE    = (240, 112, 32)    # #F07020
_C_ORANGE_BG = (254, 240, 230)   # #FEF0E6
_C_RED       = (224, 52,  72)    # #E03448
_C_RED_BG    = (253, 234, 234)   # #FDEAEA


def _score_color(trust_score: float) -> tuple[int, int, int]:
    if trust_score >= 70:
        return _C_GREEN
    if trust_score >= 40:
        return _C_ORANGE
    return _C_RED


def _score_bg(trust_score: float) -> tuple[int, int, int]:
    if trust_score >= 70:
        return _C_GREEN_BG
    if trust_score >= 40:
        return _C_ORANGE_BG
    return _C_RED_BG


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def generate_report_pdf(report: dict[str, Any]) -> bytes:
    """Render a TrustSignal report as a PDF and return it as bytes.

    Args:
        report: Dict matching the ReportResponse schema from api/main.py.
            Required keys: session_id, recruiter_id, status, start_ts,
            trust_score, suspicion_index, flagged, flag_reason, signals.
            Optional: end_ts, turns.

    Returns:
        PDF file contents as bytes.
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    # ── Header bar ──────────────────────────────────────────────────────────
    pdf.set_fill_color(*_C_PRIMARY)
    pdf.rect(0, 0, 210, 26, style="F")

    pdf.set_xy(10, 7)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*_C_WHITE)
    pdf.cell(0, 10, "TrustSignal AI  —  Interview Authenticity Report", align="L")

    # Gold accent bar below header
    pdf.set_fill_color(*_C_GOLD)
    pdf.rect(0, 26, 210, 2, style="F")

    pdf.set_y(36)
    pdf.set_text_color(*_C_DARK)

    # ── Session metadata ─────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_C_PRIMARY)
    pdf.cell(0, 7, "SESSION SUMMARY", ln=True)
    pdf.set_fill_color(*_C_PRIMARY)
    pdf.rect(pdf.get_x(), pdf.get_y(), 24, 0.5, style="F")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_C_DARK)

    rows = [
        ("Session ID",    report["session_id"]),
        ("Recruiter ID",  report["recruiter_id"]),
        ("Status",        report["status"].upper()),
        ("Started",       _fmt_ts(report["start_ts"])),
        ("Ended",         _fmt_ts(report.get("end_ts"))),
    ]
    for label, value in rows:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_C_MID)
        pdf.cell(36, 5.5, label, align="L")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_C_DARK)
        pdf.cell(0, 5.5, str(value), ln=True)

    pdf.ln(4)

    # ── TrustScore callout ───────────────────────────────────────────────────
    trust = float(report["trust_score"])
    sc = _score_color(trust)
    sb = _score_bg(trust)

    pdf.set_fill_color(*sb)
    y_box = pdf.get_y()
    pdf.rect(10, y_box, 190, 20, style="F")

    pdf.set_fill_color(*sc)
    pdf.rect(10, y_box, 3, 20, style="F")

    pdf.set_xy(18, y_box + 3)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*sc)
    pdf.cell(40, 8, f"{trust:.1f}", align="L")

    pdf.set_xy(52, y_box + 3)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_C_MID)
    pdf.cell(0, 5, "TRUSTSCORE  /  100", ln=True)

    label_map = {
        True: "TRUSTWORTHY",
        None: "MODERATE RISK",
        False: "HIGH RISK",
    }
    verdict_key = True if trust >= 70 else (None if trust >= 40 else False)
    pdf.set_xy(52, y_box + 10)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*sc)
    pdf.cell(0, 5, label_map[verdict_key])

    pdf.set_xy(130, y_box + 3)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_C_MID)
    pdf.cell(0, 5, f"Suspicion Index:  {report['suspicion_index']:.4f}", ln=True)

    pdf.set_y(y_box + 24)
    pdf.set_text_color(*_C_DARK)

    # ── Flag alert ───────────────────────────────────────────────────────────
    if report.get("flagged") and report.get("flag_reason"):
        pdf.set_fill_color(*_C_RED_BG)
        y_alert = pdf.get_y()
        reason_lines = [ln for ln in report["flag_reason"].split("\n") if ln.strip()]
        box_h = 10 + len(reason_lines) * 6
        pdf.rect(10, y_alert, 190, box_h, style="F")

        pdf.set_fill_color(*_C_RED)
        pdf.rect(10, y_alert, 3, box_h, style="F")

        pdf.set_xy(18, y_alert + 3)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_C_RED)
        pdf.cell(0, 5, "[FLAGGED] Session Alert", ln=True)

        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*_C_DARK)
        for line in reason_lines:
            pdf.set_x(18)
            pdf.multi_cell(180, 5, line.strip())

        pdf.set_y(y_alert + box_h + 4)

    pdf.ln(2)

    # ── Signal breakdown table ───────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_C_PRIMARY)
    pdf.cell(0, 7, "SIGNAL BREAKDOWN", ln=True)
    pdf.set_fill_color(*_C_PRIMARY)
    pdf.rect(pdf.get_x(), pdf.get_y(), 24, 0.5, style="F")
    pdf.ln(3)

    # Table header
    pdf.set_fill_color(*_C_PRIMARY)
    pdf.set_text_color(*_C_WHITE)
    pdf.set_font("Helvetica", "B", 8)
    col_w = [62, 28, 26, 36, 38]
    headers = ["Signal", "Raw Score", "Weight", "Contribution", "Tier"]
    for w, h in zip(col_w, headers):
        pdf.cell(w, 7, h, border=1, fill=True, align="C")
    pdf.ln()

    # Table rows
    pdf.set_font("Helvetica", "", 8.5)
    for i, sig in enumerate(report["signals"]):
        fill = i % 2 == 0
        pdf.set_fill_color(*(_C_PRIMARY10 if fill else _C_WHITE))
        pdf.set_text_color(*_C_DARK)

        raw = float(sig["raw_score"])
        tier = "HIGH" if raw >= 0.65 else ("MEDIUM" if raw >= 0.35 else "LOW")
        tier_c = _C_RED if raw >= 0.65 else (_C_ORANGE if raw >= 0.35 else _C_GREEN)

        pdf.cell(col_w[0], 6.5, sig["signal_name"], border=1, fill=True)
        pdf.cell(col_w[1], 6.5, f"{raw:.4f}", border=1, fill=True, align="C")
        pdf.cell(col_w[2], 6.5, f"{sig['weight']:.2f}", border=1, fill=True, align="C")
        pdf.cell(col_w[3], 6.5, f"{sig['weighted_contribution']:.4f}", border=1, fill=True, align="C")
        # Tier cell — coloured text
        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(col_w[4], 6.5, "", border=1, fill=True)
        pdf.set_xy(x, y)
        pdf.set_text_color(*tier_c)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(col_w[4], 6.5, tier, border=0, align="C")
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*_C_DARK)
        pdf.ln()

    pdf.ln(4)

    # ── Signal explanations ──────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_C_PRIMARY)
    pdf.cell(0, 7, "SIGNAL EXPLANATIONS", ln=True)
    pdf.set_fill_color(*_C_PRIMARY)
    pdf.rect(pdf.get_x(), pdf.get_y(), 24, 0.5, style="F")
    pdf.ln(3)

    for sig in report["signals"]:
        raw = float(sig["raw_score"])
        sc = _score_color(100 * (1 - raw))  # invert: high raw = red

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*sc)
        pdf.cell(0, 5.5, f"{sig['signal_name']}  (score: {raw:.2f}  |  weight: {sig['weight']:.2f})", ln=True)

        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*_C_DARK)
        pdf.multi_cell(0, 5, sig["explanation"])
        pdf.ln(1.5)

    # ── Footer ───────────────────────────────────────────────────────────────
    pdf.set_y(-18)
    pdf.set_fill_color(*_C_PRIMARY)
    pdf.rect(0, pdf.get_y() - 2, 210, 18, style="F")

    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(255, 255, 255)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pdf.cell(
        0, 8,
        f"TrustSignal AI  ·  OPB · Octavio Pérez Bravo  ·  Generated {now}  ·  CONFIDENTIAL",
        align="C",
    )

    return bytes(pdf.output())
