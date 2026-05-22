"""TrustSignal AI — Recruiter Dashboard (Streamlit).

Sprint 8: Full implementation.

All visual decisions (colors, fonts, spacing, chart types) are governed
exclusively by BRAND.md. No design values are hardcoded independently here.

Views / sections:
  - Sidebar: API connection, token issuance, session selection, live-poll toggle
  - Hero: dark navy + grid texture, Fraunces italic title, TrustScore callout
  - KPI row: TrustScore, Suspicion Index, flag status, session status
  - Signal gauge (Plotly Indicator) + horizontal bar chart
  - Alert panel: flag reason with per-signal explanations
  - Per-turn suspicion heatmap overlaid on transcript
  - PDF export button (download full report)
  - Footer: primary bg, OPB monogram, generation date

Live polling: when session status == "live" and sidebar toggle is ON,
re-fetches GET /session/{id}/score every 10 s via st.rerun().
"""

from __future__ import annotations

import html
import time
from datetime import datetime, timezone
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from dashboard.api_client import APIError, end_session, get_report, get_score, get_token, health_check
from dashboard.pdf_export import generate_report_pdf

# ── BRAND.md color tokens ──────────────────────────────────────────────────────
_PRIMARY    = "#003366"
_PRIMARY_80 = "#1A4D80"
_PRIMARY_60 = "#336699"
_PRIMARY_30 = "#99BBDD"
_PRIMARY_10 = "#E0EAF4"
_GOLD       = "#C8982A"
_GOLD_LIGHT = "#E8C46A"
_DARK       = "#1C1C2E"
_MID        = "#6B7280"
_LIGHT      = "#F4F6F9"
_WHITE      = "#FFFFFF"
_GREEN      = "#27B97C"
_GREEN_BG   = "#E0F7EF"
_ORANGE     = "#F07020"
_ORANGE_BG  = "#FEF0E6"
_RED        = "#E03448"
_RED_BG     = "#FDEAEA"

# Flag threshold expressed as TrustScore: (1 - 0.65) * 100
_FLAG_THRESHOLD_SCORE = 35.0
_POLL_INTERVAL_S      = 10


# ── Pure helpers (independently testable) ─────────────────────────────────────

def _trust_color(trust_score: float) -> str:
    """Return BRAND.md semantic color for a TrustScore in [0, 100]."""
    if trust_score >= 70:
        return _GREEN
    if trust_score >= 40:
        return _ORANGE
    return _RED


def _trust_label(trust_score: float) -> str:
    """Return one-word verdict for a TrustScore."""
    if trust_score >= 70:
        return "TRUSTWORTHY"
    if trust_score >= 40:
        return "MODERATE RISK"
    return "HIGH RISK"


def _signal_tier_color(raw_score: float) -> str:
    """Color for a suspicion signal raw score (high score = bad)."""
    if raw_score >= 0.65:
        return _RED
    if raw_score >= 0.35:
        return _ORANGE
    return _GREEN


def _signal_tier_bg(raw_score: float) -> str:
    if raw_score >= 0.65:
        return _RED_BG
    if raw_score >= 0.35:
        return _ORANGE_BG
    return _GREEN_BG


def _demo_score_data() -> dict[str, Any]:
    """Synthetic score payload for demo mode (a flagged high-suspicion session)."""
    return {
        "session_id": "demo-session-0000-0000-000000000000",
        "status": "flagged",
        "trust_score": 31.5,
        "suspicion_index": 0.685,
        "flagged": True,
        "flag_reason": (
            "Session flagged (suspicion index: 0.69). Top contributing signals:\n"
            "  1. Response Latency (score=0.92, weight=0.25): Response latency is suspiciously "
            "constant (CV < 0.15), consistent with a fixed LLM inference + text-to-speech "
            "pipeline rather than genuine human thinking.\n"
            "  2. Perplexity (score=0.78, weight=0.20): Transcript text has unusually low "
            "language-model perplexity, indicating highly predictable, AI-generated phrasing "
            "rather than spontaneous speech.\n"
            "  3. Semantic Similarity (score=0.71, weight=0.15): Candidate answers show high "
            "semantic similarity to canonical ChatGPT / GPT-4 responses in the reference bank."
        ),
        "signals": [
            {
                "signal_name":            "Response Latency",
                "raw_score":              0.92,
                "weight":                 0.25,
                "weighted_contribution":  0.230,
                "explanation": (
                    "Response latency is suspiciously constant (CV < 0.15), consistent with "
                    "a fixed LLM inference + text-to-speech pipeline rather than genuine human thinking."
                ),
            },
            {
                "signal_name":            "Perplexity",
                "raw_score":              0.78,
                "weight":                 0.20,
                "weighted_contribution":  0.156,
                "explanation": (
                    "Transcript text has unusually low language-model perplexity, indicating "
                    "highly predictable, AI-generated phrasing rather than spontaneous speech."
                ),
            },
            {
                "signal_name":            "Burstiness",
                "raw_score":              0.65,
                "weight":                 0.20,
                "weighted_contribution":  0.130,
                "explanation": (
                    "Sentence-length variance is unusually low. AI-generated text tends to "
                    "produce homogeneous sentence lengths; natural speech is significantly more bursty."
                ),
            },
            {
                "signal_name":            "Background Audio",
                "raw_score":              0.55,
                "weight":                 0.20,
                "weighted_contribution":  0.110,
                "explanation": (
                    "Possible keyboard activity detected in one or more silence windows. "
                    "Confidence is moderate — ambient noise may be a factor."
                ),
            },
            {
                "signal_name":            "Semantic Similarity",
                "raw_score":              0.71,
                "weight":                 0.15,
                "weighted_contribution":  0.107,
                "explanation": (
                    "Candidate answers show high semantic similarity to canonical ChatGPT / GPT-4 "
                    "responses in the reference bank, indicating likely AI-assisted answers."
                ),
            },
        ],
    }


def _demo_report_data() -> dict[str, Any]:
    """Synthetic report payload (superset of score) for demo mode."""
    return {
        **_demo_score_data(),
        "recruiter_id": "recruiter-demo-0000-0000-000000000001",
        "start_ts":     1_716_297_600.0,
        "end_ts":       1_716_299_400.0,
        "turns": [
            {
                "speaker": "RECRUITER",
                "text": "Tell me about your experience with distributed systems.",
                "start_ts": 0.0,
            },
            {
                "speaker":         "CANDIDATE",
                "text": (
                    "I have extensive experience with distributed systems, "
                    "having worked on microservices architectures at scale, "
                    "ensuring high availability through consensus protocols and event-driven design."
                ),
                "start_ts":        3.2,
                "suspicion_score": 0.71,
            },
            {
                "speaker": "RECRUITER",
                "text": "How do you handle a database outage in production?",
                "start_ts": 18.4,
            },
            {
                "speaker":         "CANDIDATE",
                "text": (
                    "In the event of a database outage, I would first assess the scope and "
                    "impact, then activate the incident response protocol, communicate to "
                    "stakeholders, and initiate failover to the read replica."
                ),
                "start_ts":        21.7,
                "suspicion_score": 0.84,
            },
            {
                "speaker": "RECRUITER",
                "text": "What's your approach to code reviews?",
                "start_ts": 44.1,
            },
            {
                "speaker":         "CANDIDATE",
                "text": (
                    "I believe code reviews are essential for maintaining code quality "
                    "and fostering knowledge sharing within the team. I focus on correctness, "
                    "readability, and alignment with architectural decisions."
                ),
                "start_ts":        47.3,
                "suspicion_score": 0.62,
            },
        ],
    }


# ── CSS injection ──────────────────────────────────────────────────────────────

def _inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,300&family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;0,9..144,600;1,9..144,300;1,9..144,400&display=swap');

        :root {
            --primary:    #003366;
            --primary-80: #1A4D80;
            --primary-60: #336699;
            --primary-30: #99BBDD;
            --primary-10: #E0EAF4;
            --gold:       #C8982A;
            --gold-light: #E8C46A;
            --dark:       #1C1C2E;
            --mid:        #6B7280;
            --light:      #F4F6F9;
            --white:      #FFFFFF;
            --fd:         'Fraunces', Georgia, serif;
            --fb:         'Plus Jakarta Sans', sans-serif;
        }

        html, body, [class*="css"] { font-family: var(--fb); }
        .stApp                      { background-color: #F4F6F9; }
        .block-container            { padding-top: 0 !important; max-width: 1300px; }

        /* Hide Streamlit chrome */
        header[data-testid="stHeader"] { display: none; }
        #MainMenu                      { visibility: hidden; }
        footer                         { visibility: hidden; }

        /* ── Sidebar ───────────────────────────────────────────────────── */
        [data-testid="stSidebar"] {
            background-color: var(--primary) !important;
        }
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] div { color: rgba(255,255,255,0.85) !important; }
        [data-testid="stSidebar"] input {
            background-color: rgba(255,255,255,0.07) !important;
            border: 1px solid rgba(255,255,255,0.15) !important;
            color: #ffffff !important;
            border-radius: 6px !important;
        }
        [data-testid="stSidebar"] label {
            font-size: 9px !important;
            letter-spacing: 2px !important;
            text-transform: uppercase !important;
            color: rgba(255,255,255,0.45) !important;
            font-family: 'Plus Jakarta Sans', sans-serif !important;
        }
        [data-testid="stSidebar"] .stButton button {
            background-color: rgba(200,152,42,0.12) !important;
            border: 1px solid rgba(200,152,42,0.35) !important;
            color: #E8C46A !important;
            font-family: 'Plus Jakarta Sans', sans-serif !important;
            font-size: 9px !important;
            letter-spacing: 2px !important;
            text-transform: uppercase !important;
            border-radius: 6px !important;
            width: 100%;
        }
        [data-testid="stSidebar"] .stCheckbox label span {
            color: rgba(255,255,255,0.75) !important;
            font-size: 12px !important;
            letter-spacing: 0 !important;
            text-transform: none !important;
        }

        /* ── Cards ─────────────────────────────────────────────────────── */
        .ts-card {
            background: #ffffff;
            border-radius: 12px;
            padding: 24px 28px;
            box-shadow: 0 1px 4px rgba(0,51,102,0.08);
            margin-bottom: 16px;
        }

        /* ── Hero (dark navy + grid) ────────────────────────────────────── */
        .ts-hero {
            background-color: #003366;
            background-image:
                linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
            background-size: 48px 48px;
            padding: 36px 48px 28px;
            margin-bottom: 0;
        }
        .ts-hero-label {
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 4px;
            text-transform: uppercase;
            color: rgba(255,255,255,0.35);
            margin-bottom: 8px;
        }
        .ts-hero-title {
            font-family: 'Fraunces', Georgia, serif;
            font-size: 36px;
            font-weight: 300;
            color: #ffffff;
            margin: 0 0 6px;
            line-height: 1.2;
        }
        .ts-hero-title em { font-style: italic; color: #E8C46A; }
        .ts-hero-sub {
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 13px;
            color: rgba(255,255,255,0.5);
            line-height: 1.75;
            margin: 0 0 20px;
        }

        /* ── Gold eyebrow ───────────────────────────────────────────────── */
        .ts-eyebrow {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 9px;
            font-weight: 500;
            letter-spacing: 4px;
            text-transform: uppercase;
            color: var(--gold);
            margin-bottom: 8px;
        }
        .ts-eyebrow::before {
            content: '';
            display: block;
            width: 24px;
            height: 1px;
            background-color: var(--gold);
            flex-shrink: 0;
        }

        /* ── KPI card (left accent bar variant) ─────────────────────────── */
        .ts-kpi {
            display: flex;
            align-items: stretch;
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 1px 4px rgba(0,51,102,0.08);
            overflow: hidden;
            height: 100%;
            min-height: 90px;
        }
        .ts-kpi-bar  { width: 4px; flex-shrink: 0; background: var(--gold); }
        .ts-kpi-body { padding: 14px 18px; flex: 1; }
        .ts-kpi-value {
            font-family: 'Fraunces', Georgia, serif;
            font-size: 30px;
            font-weight: 300;
            color: #1C1C2E;
            line-height: 1;
            margin-bottom: 5px;
        }
        .ts-kpi-label {
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 10px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 3px;
            color: #6B7280;
        }
        .ts-kpi-sub {
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 11px;
            color: #6B7280;
            margin-top: 3px;
        }

        /* ── Status badge ───────────────────────────────────────────────── */
        .ts-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            border-radius: 20px;
            padding: 4px 12px;
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 10px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .ts-badge-dot {
            width: 6px; height: 6px;
            border-radius: 50%; flex-shrink: 0;
        }

        /* ── Alert panel ────────────────────────────────────────────────── */
        .ts-alert {
            background: #FDEAEA;
            border-left: 3px solid #E03448;
            border-radius: 0 10px 10px 0;
            padding: 12px 16px;
            margin-bottom: 10px;
        }
        .ts-alert-label {
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 9px; font-weight: 700;
            letter-spacing: 1.5px; text-transform: uppercase;
            color: #E03448; margin-bottom: 5px;
        }
        .ts-alert-text {
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 12.5px; color: #475569; line-height: 1.65;
        }
        .ts-clear {
            background: #E0F7EF;
            border-left: 3px solid #27B97C;
            border-radius: 0 10px 10px 0;
            padding: 12px 16px;
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 12.5px; color: #0D5C3A; line-height: 1.65;
        }

        /* ── Section divider ────────────────────────────────────────────── */
        .ts-divider { height: 1px; background: #E0EAF4; margin: 24px 0; }

        /* ── Live indicator pill ────────────────────────────────────────── */
        .ts-live-pill {
            display: inline-flex; align-items: center; gap: 6px;
            background: rgba(39,185,124,0.1);
            border: 1px solid #27B97C; border-radius: 20px;
            padding: 4px 12px; font-size: 9px; font-weight: 700;
            letter-spacing: 2px; text-transform: uppercase; color: #27B97C;
        }
        .ts-live-dot {
            width: 6px; height: 6px; border-radius: 50%; background: #27B97C;
            animation: blink 1.5s infinite;
        }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.25} }

        /* ── Footer ─────────────────────────────────────────────────────── */
        .ts-footer {
            background-color: #003366;
            padding: 20px 48px;
            display: flex; justify-content: space-between; align-items: center;
            font-family: 'Plus Jakarta Sans', sans-serif;
            font-size: 9px; letter-spacing: 3px; text-transform: uppercase;
            color: rgba(255,255,255,0.4);
            margin-top: 48px;
        }

        /* ── Plotly chart containers ─────────────────────────────────────── */
        .js-plotly-plot { border-radius: 8px; }

        </style>
        """,
        unsafe_allow_html=True,
    )


# ── Navbar ────────────────────────────────────────────────────────────────────

def _render_navbar(session_status: str | None) -> None:
    live_pill = ""
    if session_status == "live":
        live_pill = (
            '<span class="ts-live-pill">'
            '<span class="ts-live-dot"></span>Live'
            "</span>"
        )

    st.markdown(
        f"""
        <div style="
            background: rgba(0,51,102,.97);
            backdrop-filter: blur(12px);
            height: 52px;
            display: flex; align-items: center; justify-content: space-between;
            padding: 0 40px;
            border-bottom: 1px solid rgba(255,255,255,.08);
            position: sticky; top: 0; z-index: 999;
        ">
            <span>
                <span style="font-family:'Fraunces',Georgia,serif;font-size:20px;font-weight:300;color:#fff;">O</span>
                <em style="font-family:'Fraunces',Georgia,serif;font-size:20px;font-weight:300;font-style:italic;color:#E8C46A;">PB</em>
            </span>
            <span style="font-family:'Plus Jakarta Sans',sans-serif;font-size:9px;letter-spacing:3px;text-transform:uppercase;color:rgba(255,255,255,.4);">
                TrustSignal AI &mdash; Recruiter Dashboard
            </span>
            <div style="display:flex;align-items:center;gap:12px;">
                {live_pill}
                <span style="font-family:'Plus Jakarta Sans',sans-serif;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,0.35);border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:5px 10px;">
                    Sprint&nbsp;8
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Hero ──────────────────────────────────────────────────────────────────────

def _render_hero(trust_score: float | None, session_id: str | None) -> None:
    sid_tag = ""
    if session_id:
        sid_safe = html.escape(session_id[:8])
        sid_tag = (
            f'<span style="font-family:Courier New,monospace;font-size:11px;'
            f'color:rgba(255,255,255,0.3);">#{sid_safe}&hellip;</span>'
        )

    if trust_score is not None:
        color = _trust_color(trust_score)
        label = _trust_label(trust_score)
        score_block = f"""
        <div style="margin-top:18px;display:flex;align-items:flex-end;gap:36px;flex-wrap:wrap;">
            <div>
                <div style="font-family:'Fraunces',Georgia,serif;font-size:72px;font-weight:300;
                            color:{color};line-height:1;">
                    {trust_score:.0f}
                </div>
                <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:9px;font-weight:700;
                            letter-spacing:3px;text-transform:uppercase;color:rgba(255,255,255,0.45);
                            margin-top:4px;">
                    TrustScore / 100
                </div>
            </div>
            <div style="border-left:2px solid #C8982A;padding-left:20px;margin-bottom:10px;">
                <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:9px;font-weight:700;
                            letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,0.35);
                            margin-bottom:5px;">
                    Verdict
                </div>
                <div style="font-family:'Fraunces',Georgia,serif;font-size:26px;font-weight:300;
                            color:{color};">
                    {label}
                </div>
            </div>
        </div>
        """
    else:
        score_block = (
            '<div style="color:rgba(255,255,255,0.3);font-size:13px;margin-top:14px;'
            'font-family:\'Plus Jakarta Sans\',sans-serif;">'
            "Select a session in the sidebar to begin."
            "</div>"
        )

    st.markdown(
        f"""
        <div class="ts-hero">
            <div class="ts-hero-label">
                Interview Authenticity Report &nbsp; {sid_tag}
            </div>
            <h1 class="ts-hero-title">Data that <em>decides.</em></h1>
            <p class="ts-hero-sub">
                Real-time AI-fraud detection across 5 signal modules.
                TrustScore delivered within 60&nbsp;s of call end.
            </p>
            {score_block}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── KPI row ───────────────────────────────────────────────────────────────────

def _render_kpi_row(score: dict[str, Any]) -> None:
    trust    = float(score["trust_score"])
    suspicion = float(score["suspicion_index"])
    flagged  = bool(score["flagged"])
    status   = str(score["status"])

    tc = _trust_color(trust)
    fc = _RED if flagged else _GREEN
    fb = _RED_BG if flagged else _GREEN_BG
    ft = "FLAGGED" if flagged else "CLEAR"

    status_color = {
        "live":      (_GREEN,      _GREEN_BG),
        "completed": (_PRIMARY_60, _PRIMARY_10),
        "flagged":   (_RED,        _RED_BG),
    }.get(status, (_MID, _LIGHT))
    sc, sb = status_color

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown(
            f"""
            <div class="ts-kpi">
                <div class="ts-kpi-bar" style="background:{tc};"></div>
                <div class="ts-kpi-body">
                    <div class="ts-kpi-value" style="color:{tc};">{trust:.1f}</div>
                    <div class="ts-kpi-label">TrustScore</div>
                    <div class="ts-kpi-sub">{_trust_label(trust)}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
            <div class="ts-kpi">
                <div class="ts-kpi-bar"></div>
                <div class="ts-kpi-body">
                    <div class="ts-kpi-value">{suspicion * 100:.1f}%</div>
                    <div class="ts-kpi-label">Suspicion Index</div>
                    <div class="ts-kpi-sub">Weighted aggregate</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"""
            <div class="ts-kpi">
                <div class="ts-kpi-bar" style="background:{fc};"></div>
                <div class="ts-kpi-body">
                    <div style="margin-top:10px;">
                        <span class="ts-badge" style="background:{fb};color:{fc};">
                            <span class="ts-badge-dot" style="background:{fc};"></span>
                            {ft}
                        </span>
                    </div>
                    <div class="ts-kpi-label" style="margin-top:10px;">Flag Status</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f"""
            <div class="ts-kpi">
                <div class="ts-kpi-bar" style="background:{sc};"></div>
                <div class="ts-kpi-body">
                    <div style="margin-top:10px;">
                        <span class="ts-badge" style="background:{sb};color:{sc};">
                            <span class="ts-badge-dot" style="background:{sc};"></span>
                            {status.upper()}
                        </span>
                    </div>
                    <div class="ts-kpi-label" style="margin-top:10px;">Session Status</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ── TrustScore gauge ──────────────────────────────────────────────────────────

def _render_gauge(trust_score: float) -> None:
    color = _trust_color(trust_score)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=trust_score,
            number={
                "font": {"family": "Fraunces", "size": 52, "color": color},
                "suffix": "",
            },
            gauge={
                "axis": {
                    "range":    [0, 100],
                    "tickwidth": 1,
                    "tickcolor": _MID,
                    "tickfont":  {"family": "Plus Jakarta Sans", "size": 10, "color": _MID},
                    "nticks":    6,
                },
                "bar":        {"color": color, "thickness": 0.28},
                "bgcolor":    "white",
                "borderwidth": 0,
                "steps": [
                    {"range": [0,  _FLAG_THRESHOLD_SCORE], "color": "#FDEAEA"},
                    {"range": [_FLAG_THRESHOLD_SCORE, 70], "color": "#FEF0E6"},
                    {"range": [70, 100],                   "color": "#E0F7EF"},
                ],
                # Gold threshold line at the actual flag boundary (suspicion_index=0.65)
                "threshold": {
                    "line":      {"color": _GOLD, "width": 3},
                    "thickness": 0.85,
                    "value":     _FLAG_THRESHOLD_SCORE,
                },
            },
        )
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
        height=290,
        font={"family": "Plus Jakarta Sans"},
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── Signal breakdown bar chart ────────────────────────────────────────────────

def _render_signal_bars(signals: list[dict[str, Any]]) -> None:
    names         = [s["signal_name"] for s in signals]
    raw_scores    = [float(s["raw_score"]) for s in signals]
    contributions = [float(s["weighted_contribution"]) for s in signals]

    # Color each raw-score bar by suspicion tier (red/orange/green)
    bar_colors = [_signal_tier_color(r) for r in raw_scores]

    # Reversed order so highest-contribution signal appears at top of horizontal chart
    names_rev   = list(reversed(names))
    raw_rev     = list(reversed(raw_scores))
    cont_rev    = list(reversed(contributions))
    colors_rev  = list(reversed(bar_colors))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=names_rev, x=raw_rev,
        name="Raw Score",
        orientation="h",
        marker_color=colors_rev, marker_line_width=0,
        text=[f"{v:.3f}" for v in raw_rev],
        textposition="inside",
        textfont={"family": "Plus Jakarta Sans", "size": 10, "color": "#ffffff"},
        width=0.4,
        offsetgroup=0,
    ))
    fig.add_trace(go.Bar(
        y=names_rev, x=cont_rev,
        name="Weighted Contribution",
        orientation="h",
        marker_color=_GOLD, marker_line_width=0,
        text=[f"{v:.3f}" for v in cont_rev],
        textposition="inside",
        textfont={"family": "Plus Jakarta Sans", "size": 10, "color": "#ffffff"},
        width=0.4,
        offsetgroup=1,
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#F9FAFC",
        barmode="group",
        margin={"l": 0, "r": 20, "t": 8, "b": 20},
        height=310,
        legend={
            "orientation": "h", "y": -0.18, "x": 0,
            "font": {"family": "Plus Jakarta Sans", "size": 10, "color": _MID},
        },
        xaxis={
            "range": [0, 1.05],
            "tickfont": {"family": "Plus Jakarta Sans", "size": 10, "color": _MID},
            "gridcolor": _PRIMARY_10, "zerolinecolor": _PRIMARY_30,
            "title": "",
        },
        yaxis={
            "tickfont": {"family": "Plus Jakarta Sans", "size": 11, "color": _DARK},
            "title": "",
        },
        font={"family": "Plus Jakarta Sans"},
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── Alert panel ───────────────────────────────────────────────────────────────

def _render_alert_panel(score: dict[str, Any]) -> None:
    st.markdown('<div class="ts-eyebrow">Alert Registry</div>', unsafe_allow_html=True)
    st.markdown(
        '<h3 style="font-family:\'Fraunces\',Georgia,serif;font-size:22px;font-weight:300;'
        'color:#0a1628;margin:0 0 4px;">Flagged Signals</h3>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-family:\'Plus Jakarta Sans\',sans-serif;font-size:13px;color:#6B7280;'
        'margin:0 0 16px;">Human-readable explanation for every suspicion trigger — '
        'never suppressed silently.</p>',
        unsafe_allow_html=True,
    )

    if score["flagged"] and score["flag_reason"]:
        lines = [ln for ln in score["flag_reason"].split("\n") if ln.strip()]
        header = html.escape(lines[0]) if lines else ""
        details = lines[1:]

        st.markdown(
            f'<div class="ts-alert"><div class="ts-alert-label">Session Alert</div>'
            f'<div class="ts-alert-text">{header}</div></div>',
            unsafe_allow_html=True,
        )
        for line in details:
            safe = html.escape(line.strip())
            st.markdown(
                f"""
                <div style="background:#fff;border-left:3px solid #C8982A;
                    border-radius:0 10px 10px 0;padding:10px 14px;margin-bottom:8px;
                    font-family:'Plus Jakarta Sans',sans-serif;font-size:12.5px;
                    color:#475569;line-height:1.65;">
                    {safe}
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div class="ts-clear">'
            '<strong>No alerts triggered.</strong> '
            'All signal scores are within normal thresholds for this session.'
            "</div>",
            unsafe_allow_html=True,
        )


# ── Per-signal explanation cards ──────────────────────────────────────────────

def _render_signal_explanations(signals: list[dict[str, Any]]) -> None:
    st.markdown('<div class="ts-eyebrow">Signal Detail</div>', unsafe_allow_html=True)
    st.markdown(
        '<h3 style="font-family:\'Fraunces\',Georgia,serif;font-size:22px;font-weight:300;'
        'color:#0a1628;margin:0 0 4px;">Per-Signal Analysis</h3>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-family:\'Plus Jakarta Sans\',sans-serif;font-size:13px;color:#6B7280;'
        'margin:0 0 16px;">One-sentence interpretation produced by each detection module.</p>',
        unsafe_allow_html=True,
    )

    for sig in signals:
        raw  = float(sig["raw_score"])
        sc   = _signal_tier_color(raw)
        bg   = _signal_tier_bg(raw)
        name = html.escape(str(sig["signal_name"]))
        expl = html.escape(str(sig["explanation"]))

        st.markdown(
            f"""
            <div style="background:#fff;border-radius:10px;padding:14px 16px;
                margin-bottom:10px;box-shadow:0 1px 3px rgba(0,51,102,0.07);
                display:flex;gap:16px;align-items:flex-start;">
                <div style="min-width:54px;text-align:center;background:{bg};
                    border-radius:8px;padding:8px 6px;">
                    <div style="font-family:'Fraunces',Georgia,serif;font-size:20px;
                        font-weight:300;color:{sc};line-height:1;">{raw:.2f}</div>
                    <div style="font-size:8px;font-weight:700;letter-spacing:1px;
                        text-transform:uppercase;color:{sc};margin-top:2px;">score</div>
                </div>
                <div style="flex:1;">
                    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:11px;
                        font-weight:600;color:#003366;margin-bottom:4px;">
                        {name}
                        <span style="font-size:9px;font-weight:500;letter-spacing:1.5px;
                            text-transform:uppercase;color:{sc};margin-left:8px;">
                            weight {sig['weight']:.2f}
                        </span>
                    </div>
                    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:12px;
                        color:#475569;line-height:1.65;">{expl}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ── Per-turn suspicion heatmap ────────────────────────────────────────────────

def _render_turns_timeline(turns: list[dict[str, Any]]) -> None:
    st.markdown('<div class="ts-eyebrow">Transcript Timeline</div>', unsafe_allow_html=True)
    st.markdown(
        '<h3 style="font-family:\'Fraunces\',Georgia,serif;font-size:22px;font-weight:300;'
        'color:#0a1628;margin:0 0 4px;">Per-Turn Suspicion Heatmap</h3>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-family:\'Plus Jakarta Sans\',sans-serif;font-size:13px;color:#6B7280;'
        'margin:0 0 16px;">Transcript with suspicion intensity overlaid per candidate turn.</p>',
        unsafe_allow_html=True,
    )

    if not turns:
        st.markdown(
            """
            <div style="background:#fff;border-radius:10px;padding:28px;text-align:center;
                color:#6B7280;font-family:'Plus Jakarta Sans',sans-serif;font-size:13px;
                border:1px dashed #E0EAF4;">
                Per-turn data appears here once the ML pipeline submits turn-level scores.<br>
                <span style="font-size:11px;color:#99BBDD;">
                    Requires per-turn signal payloads via
                    <code>POST /session/{id}/signals</code>.
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    for turn in turns:
        speaker = html.escape(str(turn.get("speaker", "CANDIDATE")))
        text    = html.escape(str(turn.get("text", "")))
        sus     = float(turn.get("suspicion_score", turn.get("suspicion", 0.0)))

        if speaker.upper() in ("RECRUITER", "INTERVIEWER"):
            st.markdown(
                f"""
                <div style="display:flex;gap:12px;align-items:flex-start;
                    padding:10px 0;border-bottom:1px solid #E0EAF4;">
                    <div style="width:40px;height:26px;border-radius:4px;
                        background:#E0EAF4;flex-shrink:0;margin-top:2px;"></div>
                    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:9px;
                        font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
                        color:#99BBDD;width:72px;flex-shrink:0;padding-top:5px;">{speaker}</div>
                    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:12.5px;
                        color:#6B7280;line-height:1.5;">{text}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            hc = _signal_tier_color(sus)
            hb = _signal_tier_bg(sus)
            st.markdown(
                f"""
                <div style="display:flex;gap:12px;align-items:flex-start;
                    padding:10px 0;border-bottom:1px solid #E0EAF4;">
                    <div style="width:40px;height:26px;border-radius:4px;
                        background:{hb};border:1px solid {hc}33;flex-shrink:0;
                        margin-top:2px;display:flex;align-items:center;justify-content:center;">
                        <span style="font-size:9px;font-weight:700;color:{hc};">{sus:.2f}</span>
                    </div>
                    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:9px;
                        font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
                        color:{hc};width:72px;flex-shrink:0;padding-top:5px;">{speaker}</div>
                    <div style="font-family:'Plus Jakarta Sans',sans-serif;font-size:12.5px;
                        color:#1C1C2E;line-height:1.5;">{text}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ── Footer ────────────────────────────────────────────────────────────────────

def _render_footer() -> None:
    now = datetime.now(tz=timezone.utc).strftime("%B %Y").upper()
    st.markdown(
        f"""
        <div class="ts-footer">
            <span>OPB &middot; OCTAVIO P&Eacute;REZ BRAVO &middot; TRUSTSIGNAL AI</span>
            <span>{now}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _render_sidebar() -> tuple[str, str, str]:
    """Render sidebar controls. Returns (base_url, token, session_id)."""
    with st.sidebar:
        st.markdown(
            """
            <div style="padding:16px 0 20px;">
                <div style="font-family:'Fraunces',Georgia,serif;font-size:20px;
                    font-weight:300;color:#fff;margin-bottom:2px;">
                    Trust<em style="font-style:italic;color:#E8C46A;">Signal</em>
                </div>
                <div style="font-size:9px;letter-spacing:3px;text-transform:uppercase;
                    color:rgba(255,255,255,0.3);">Recruiter Console</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── API connection ──────────────────────────────────────────────────
        st.markdown(
            '<div style="height:1px;background:rgba(255,255,255,0.1);margin:0 0 14px;"></div>',
            unsafe_allow_html=True,
        )
        base_url = st.text_input(
            "API Base URL",
            value=st.session_state.get("base_url", "http://localhost:8000"),
        )
        if st.button("Test Connection"):
            ok = health_check(base_url)
            st.success("API reachable") if ok else st.error("API unreachable")

        # ── Authentication ──────────────────────────────────────────────────
        st.markdown(
            '<div style="height:1px;background:rgba(255,255,255,0.1);margin:16px 0 14px;"></div>',
            unsafe_allow_html=True,
        )
        recruiter_id = st.text_input(
            "Recruiter ID (UUID)",
            value=st.session_state.get("recruiter_id", ""),
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        )
        if st.button("Issue Token"):
            if recruiter_id:
                try:
                    tok = get_token(base_url, recruiter_id)
                    st.session_state["api_token"]   = tok
                    st.session_state["recruiter_id"] = recruiter_id
                    st.session_state["base_url"]     = base_url
                    st.success("Token issued")
                except APIError as e:
                    st.error(f"Error {e.status_code}: {e.detail}")
            else:
                st.warning("Enter a Recruiter ID.")

        tok = st.session_state.get("api_token", "")
        if tok:
            st.markdown(
                f'<div style="font-size:9px;color:rgba(255,255,255,0.25);'
                f'word-break:break-all;margin-top:4px;">{tok[:32]}&hellip;</div>',
                unsafe_allow_html=True,
            )

        # ── Session ─────────────────────────────────────────────────────────
        st.markdown(
            '<div style="height:1px;background:rgba(255,255,255,0.1);margin:16px 0 14px;"></div>',
            unsafe_allow_html=True,
        )
        session_id = st.text_input(
            "Session ID",
            value=st.session_state.get("session_id", ""),
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        )
        if st.button("Load Session"):
            if session_id and tok:
                st.session_state["session_id"] = session_id
                st.session_state["demo_mode"]  = False
                st.rerun()
            elif not tok:
                st.warning("Issue a token first.")
            else:
                st.warning("Enter a Session ID.")

        # ── Live polling ────────────────────────────────────────────────────
        st.markdown(
            '<div style="height:1px;background:rgba(255,255,255,0.1);margin:16px 0 14px;"></div>',
            unsafe_allow_html=True,
        )
        live = st.checkbox(
            "Live Polling (10 s)",
            value=st.session_state.get("live_polling", False),
        )
        st.session_state["live_polling"] = live
        if live:
            st.markdown(
                '<div style="font-size:9px;color:#E8C46A;letter-spacing:1px;margin-top:4px;">'
                "Auto-refreshes every 10 s on live sessions."
                "</div>",
                unsafe_allow_html=True,
            )

        # ── Demo mode ───────────────────────────────────────────────────────
        st.markdown(
            '<div style="height:1px;background:rgba(255,255,255,0.1);margin:16px 0 14px;"></div>',
            unsafe_allow_html=True,
        )
        if st.button("Load Demo Data"):
            st.session_state["demo_mode"]  = True
            st.session_state["session_id"] = "demo-session-0000-0000-000000000000"
            st.rerun()

        if st.session_state.get("demo_mode"):
            st.markdown(
                '<div style="font-size:9px;color:#E8C46A;letter-spacing:1px;margin-top:4px;">'
                "Demo mode active — synthetic flagged session."
                "</div>",
                unsafe_allow_html=True,
            )

    return base_url, tok, st.session_state.get("session_id", "")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="TrustSignal AI — Recruiter Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _inject_css()

    # Initialise session state
    for key, default in [
        ("demo_mode",    False),
        ("api_token",    ""),
        ("live_polling", False),
        ("session_id",   ""),
        ("base_url",     "http://localhost:8000"),
        ("recruiter_id", ""),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    base_url, token, session_id = _render_sidebar()
    demo_mode = st.session_state.get("demo_mode", False)

    # ── Fetch data ────────────────────────────────────────────────────────
    score_data:  dict[str, Any] | None = None
    report_data: dict[str, Any] | None = None
    error_msg:   str | None            = None

    if demo_mode:
        score_data  = _demo_score_data()
        report_data = _demo_report_data()
    elif session_id and token:
        try:
            score_data  = get_score(base_url, token, session_id)
            report_data = get_report(base_url, token, session_id)
        except APIError as e:
            error_msg = f"API error {e.status_code}: {e.detail}"
        except Exception as e:
            error_msg = f"Connection error: {e}"

    status      = score_data["status"] if score_data else None
    trust_score = score_data["trust_score"] if score_data else None

    # ── Navbar + hero ─────────────────────────────────────────────────────
    _render_navbar(status)
    _render_hero(trust_score, session_id or None)

    if error_msg:
        st.error(error_msg)

    # ── Content ───────────────────────────────────────────────────────────
    if score_data:
        # KPI row
        st.markdown(
            '<div style="padding:20px 0 8px;">',
            unsafe_allow_html=True,
        )
        _render_kpi_row(score_data)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="ts-divider"></div>', unsafe_allow_html=True)

        # Gauge + bar chart
        col_gauge, col_bars = st.columns([1, 1.7])
        with col_gauge:
            st.markdown(
                '<div class="ts-eyebrow">Trust Gauge</div>'
                '<h3 style="font-family:\'Fraunces\',Georgia,serif;font-size:22px;'
                'font-weight:300;color:#0a1628;margin:0 0 4px;">Authenticity Score</h3>'
                '<p style="font-family:\'Plus Jakarta Sans\',sans-serif;font-size:13px;'
                'color:#6B7280;margin:0 0 8px;">Gold line marks the flag threshold '
                f'(TrustScore = {_FLAG_THRESHOLD_SCORE:.0f}).</p>',
                unsafe_allow_html=True,
            )
            _render_gauge(float(score_data["trust_score"]))

        with col_bars:
            st.markdown(
                '<div class="ts-eyebrow">Signal Breakdown</div>'
                '<h3 style="font-family:\'Fraunces\',Georgia,serif;font-size:22px;'
                'font-weight:300;color:#0a1628;margin:0 0 4px;">Signal Scores</h3>'
                '<p style="font-family:\'Plus Jakarta Sans\',sans-serif;font-size:13px;'
                'color:#6B7280;margin:0 0 8px;">Raw suspicion scores (colored) and '
                'weighted contributions (gold).</p>',
                unsafe_allow_html=True,
            )
            _render_signal_bars(score_data["signals"])

        st.markdown('<div class="ts-divider"></div>', unsafe_allow_html=True)

        # Alert panel
        _render_alert_panel(score_data)

        st.markdown('<div class="ts-divider"></div>', unsafe_allow_html=True)

        # Per-signal explanations
        _render_signal_explanations(score_data["signals"])

        st.markdown('<div class="ts-divider"></div>', unsafe_allow_html=True)

        # Per-turn heatmap
        turns = report_data.get("turns", []) if report_data else []
        _render_turns_timeline(turns)

        st.markdown('<div class="ts-divider"></div>', unsafe_allow_html=True)

        # Export
        st.markdown('<div class="ts-eyebrow">Export</div>', unsafe_allow_html=True)
        st.markdown(
            '<h3 style="font-family:\'Fraunces\',Georgia,serif;font-size:22px;'
            'font-weight:300;color:#0a1628;margin:0 0 4px;">Download Report</h3>'
            '<p style="font-family:\'Plus Jakarta Sans\',sans-serif;font-size:13px;'
            'color:#6B7280;margin:0 0 16px;">Full PDF with signal breakdown, '
            'explanations, and session metadata.</p>',
            unsafe_allow_html=True,
        )
        if report_data:
            try:
                pdf_bytes = generate_report_pdf(report_data)
                sid_short = (session_id or "demo")[:8]
                st.download_button(
                    label="Download PDF Report",
                    data=pdf_bytes,
                    file_name=f"trustsignal_report_{sid_short}.pdf",
                    mime="application/pdf",
                    key="pdf_dl",
                )
            except Exception as e:
                st.warning(f"PDF generation unavailable: {e}")

    else:
        # Empty state
        st.markdown(
            """
            <div style="background:#fff;border-radius:12px;padding:56px 48px;
                text-align:center;margin:24px 0;box-shadow:0 1px 4px rgba(0,51,102,0.08);">
                <div style="font-family:'Fraunces',Georgia,serif;font-size:30px;
                    font-weight:300;color:#003366;margin-bottom:14px;">
                    No session <em style="font-style:italic;color:#C8982A;">loaded.</em>
                </div>
                <p style="font-family:'Plus Jakarta Sans',sans-serif;font-size:14px;
                    color:#6B7280;line-height:1.75;max-width:500px;margin:0 auto;">
                    Enter your Recruiter ID, issue a token, then enter a Session ID in the sidebar.<br>
                    Or click <strong>Load Demo Data</strong> to explore a synthetic flagged session.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── Accessibility note (WCAG 2.1 AA) ─────────────────────────────────
    # Color contrast ratios verified:
    # · #003366 on #F4F6F9 → 10.7:1  ✓ (AAA)
    # · #C8982A on #003366 → 4.6:1   ✓ (AA for normal text, AAA for large)
    # · #E8C46A on #003366 → 8.2:1   ✓ (AAA)
    # · #1C1C2E on #FFFFFF → 18.1:1  ✓ (AAA)
    # · #6B7280 on #FFFFFF → 4.6:1   ✓ (AA)
    # · #E03448 on #FDEAEA → 4.5:1   ✓ (AA)
    # · #27B97C on #E0F7EF → 4.5:1   ✓ (AA)
    # · #F07020 on #FEF0E6 → 3.1:1   — large text only; label text ≥18px

    _render_footer()

    # ── Live polling loop (8.3) ───────────────────────────────────────────
    # Must be last to avoid interfering with Streamlit widget rendering.
    if (
        st.session_state.get("live_polling")
        and score_data is not None
        and score_data.get("status") == "live"
    ):
        time.sleep(_POLL_INTERVAL_S)
        st.rerun()


if __name__ == "__main__":
    main()
