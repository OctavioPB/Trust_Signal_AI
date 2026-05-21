"""TrustSignal AI — Recruiter Dashboard (Streamlit).

All visual decisions (colors, fonts, spacing, chart types) are governed
exclusively by BRAND.md. Do not hardcode any design values here.

Views:
  - Session selector (by recruiter org, date range)
  - Hero metric: TrustScore gauge (0–100)
  - Signal breakdown bar chart
  - Per-turn suspicion heatmap overlaid on transcript
  - Alert panel with human-readable explanations

Live polling: GET /session/{id}/score every 10 s during active calls.

Implemented in Sprint 8.
"""

from __future__ import annotations

import streamlit as st


def main() -> None:
    """Entry point for the Streamlit dashboard."""
    st.set_page_config(
        page_title="TrustSignal AI",
        page_icon="🔍",
        layout="wide",
    )

    st.title("TrustSignal AI")
    st.info(
        "Dashboard UI will be implemented in Sprint 8. "
        "All styling follows BRAND.md tokens."
    )


if __name__ == "__main__":
    main()
