"""
ui/components.py — Reusable UI components shared across tabs.

Includes:
  - render_explainability_panel()  Phase 2 explainability panel
  - show_result()                  Full triage result display (Phases 1-3)
"""
import json
from datetime import datetime

import streamlit as st

# Phase 3 — override reason categories
OVERRIDE_REASONS = [
    "-- Select reason --",
    "Disagree with triage level",
    "Missing clinical context",
    "Patient preference",
    "Clinical judgement",
    "Other",
]


def _confidence_plain_english(confidence_raw: str) -> tuple[str, str]:
    """Return (plain-English text, NHS hex colour) from the raw confidence string."""
    low = confidence_raw.lower()
    if "high" in low:
        return (
            "The AI has **high confidence** in this recommendation. "
            "The presentation closely matches multiple validated training cases.",
            "#009639",
        )
    if "medium" in low:
        return (
            "The AI has **medium confidence**. The presentation partially matches "
            "known patterns. Additional clinical assessment is advised.",
            "#FFB81C",
        )
    return (
        "The AI has **low confidence**. The presentation contains unusual features. "
        "Extra clinical care and judgement are essential.",
        "#DA291C",
    )


def render_explainability_panel(result: dict) -> None:
    """Show top-3 matched cases and a plain-English confidence explanation."""
    similar_cases = result.get("similar_cases", [])
    if not similar_cases:
        return

    with st.expander("How the AI reached this decision", expanded=True):
        plain_conf, _ = _confidence_plain_english(result.get("confidence", ""))
        st.info(plain_conf)

        st.markdown("**Top matching cases from the validated training dataset:**")

        cols = st.columns(len(similar_cases))
        badge_colors = {"RED": "#DA291C", "AMBER": "#FFB81C", "GREEN": "#009639"}

        for col, case in zip(cols, similar_cases):
            triage = case.get("triage_decision", "Unknown")
            sim_pct = min(case.get("similarity_pct", 0), 100)
            badge_color = badge_colors.get(triage, "#AEB7BD")

            with col:
                st.markdown(
                    f"**Match {case['rank']}** "
                    f'<span style="background:{badge_color};color:white;padding:2px 8px;'
                    f'border-radius:3px;font-size:0.78rem;font-weight:700">{triage}</span>',
                    unsafe_allow_html=True,
                )
                st.markdown(f"*{case.get('chief_complaint', 'Similar presentation')}*")
                st.progress(sim_pct / 100, text=f"{sim_pct:.0f}% similarity")
                st.caption(f"Urgency: {case.get('urgency_timeframe', 'N/A')}")
                st.caption(f"{case.get('presentation_snippet', '')[:180]}...")


def show_result(result: dict, patient_description: str, case_idx: int) -> None:
    """Render the triage decision card only. Detail tabs are rendered in triage_tab.py."""
    triage  = result["triage_decision"]
    urgency = result["urgency_timeframe"]

    # Phase 1 — Triage card with NHS colours
    if triage == "RED":
        st.markdown(
            f'<div class="triage-red">'
            f'<h2>TRIAGE: RED — Emergency</h2>'
            f'<h3>Urgency: {urgency}</h3>'
            f'</div>',
            unsafe_allow_html=True,
        )
    elif triage == "AMBER":
        st.markdown(
            f'<div class="triage-amber">'
            f'<h2>TRIAGE: AMBER — Urgent</h2>'
            f'<h3>Urgency: {urgency}</h3>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="triage-green">'
            f'<h2>TRIAGE: GREEN — Routine</h2>'
            f'<h3>Urgency: {urgency}</h3>'
            f'</div>',
            unsafe_allow_html=True,
        )

    response_time = st.session_state.triage_history[case_idx].get("response_time")
    if response_time:
        st.caption(f"Analysis completed in {response_time}s")
