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
    """Render the full triage result: card, explainability, clinical detail, export, override."""
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

    # Phase 2 — Explainability
    st.markdown("---")
    render_explainability_panel(result)

    # Clinical detail
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Clinical Reasoning")
        st.write(result["clinical_reasoning"])
        st.subheader("Recommended Action")
        st.info(result["recommended_action"])
    with col2:
        st.subheader("Red Flags")
        if result["red_flags"].lower() == "none identified":
            st.success("None identified")
        else:
            st.warning(result["red_flags"])
        st.subheader("NICE Guideline")
        st.write(result["nice_guideline"])
        st.subheader("Confidence")
        confidence = result["confidence"]
        if "high" in confidence.lower():
            st.success(confidence)
        elif "medium" in confidence.lower():
            st.warning(confidence)
        else:
            st.error(confidence)

    # Differential diagnosis
    st.markdown("---")
    st.subheader("Differential Diagnosis")
    d1, d2, d3 = st.columns(3)
    with d1:
        st.markdown("**Could also be:**")
        st.info(result.get("differentials", "Not specified"))
    with d2:
        st.markdown("**Rule out first:**")
        st.error(result.get("rule_out", "Not specified"))
    with d3:
        st.markdown("**Ask the patient:**")
        st.warning(result.get("follow_up_questions", "Not specified"))

    # Raw response
    st.markdown("---")
    with st.expander("Raw AI response"):
        st.code(result["raw_response"], language="text")

    # Phase 3 — Per-case export (JSON + CSV)
    st.markdown("---")
    st.subheader("Export This Result")
    e1, e2 = st.columns(2)
    with e1:
        export_result = {k: v for k, v in result.items() if k != "similar_cases"}
        st.download_button(
            "Download JSON",
            data=json.dumps(
                {
                    "timestamp": datetime.now().isoformat(),
                    "patient_input": patient_description,
                    "result": export_result,
                },
                indent=2,
            ),
            file_name=f"triage_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
        )
    with e2:
        csv_data = (
            f"Triage,{result['triage_decision']}\n"
            f"Urgency,{result['urgency_timeframe']}\n"
            f"Confidence,{result['confidence']}\n\n"
            f"Patient Input:\n{patient_description}\n\n"
            f"Reasoning:\n{result['clinical_reasoning']}\n\n"
            f"Recommended Action:\n{result['recommended_action']}\n\n"
            f"Differentials:\n{result.get('differentials', '')}\n\n"
            f"Rule Out:\n{result.get('rule_out', '')}\n\n"
            f"Follow Up Questions:\n{result.get('follow_up_questions', '')}"
        )
        st.download_button(
            "Download CSV",
            data=csv_data,
            file_name=f"triage_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

    # Phase 3 — Override with dropdown reason
    st.markdown("---")
    st.subheader("Clinician Override")
    existing = st.session_state.triage_history[case_idx].get("override")
    if existing:
        detail_str = f" ({existing['reason_detail']})" if existing.get("reason_detail") else ""
        st.success(
            f"Override recorded: AI said **{triage}**, clinician changed to "
            f"**{existing['decision']}** — {existing['reason']}{detail_str}"
        )
    else:
        st.caption(
            "If you disagree with the AI decision, record your override below. "
            "This is captured in the audit trail."
        )
        with st.form(key=f"override_form_{case_idx}"):
            override_decision = st.selectbox(
                "Clinician Triage Decision",
                ["-- No override --", "RED", "AMBER", "GREEN"],
            )
            override_reason = st.selectbox(
                "Reason for override",
                OVERRIDE_REASONS,
            )
            override_detail = st.text_input(
                "Additional details (optional)",
                placeholder="Any further context...",
            )
            submitted = st.form_submit_button("Submit Override")

        if submitted:
            if override_decision == "-- No override --":
                st.warning("Please select a triage level.")
            elif override_reason == "-- Select reason --":
                st.warning("Please select a reason for the override.")
            else:
                override_data = {
                    "decision": override_decision,
                    "reason": override_reason,
                    "reason_detail": override_detail.strip(),
                    "clinician_timestamp": datetime.now().isoformat(),
                    "ai_original": triage,
                }
                st.session_state.triage_history[case_idx]["override"] = override_data
                st.session_state.audit_log[case_idx]["clinician_override"] = override_data
                st.success(
                    f"Override recorded: AI said {triage}, "
                    f"clinician changed to {override_decision}"
                )
                st.rerun()
