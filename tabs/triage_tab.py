"""
tabs/triage_tab.py — Triage tab UI and logic (Phases 1, 2, 3, 4).
"""
import time
from datetime import datetime

import streamlit as st

from ui.components import show_result


def render_triage() -> None:
    """Render the Triage tab."""
    # Phase 4 — apply demo scenario pre-fill set by sidebar button
    if "load_scenario" in st.session_state:
        st.session_state["patient_input"] = st.session_state.pop("load_scenario")

    st.subheader("Patient Presentation")

    with st.expander("Example templates"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**RED Example:**")
            st.code("64M, crushing chest pain 40 min\nRadiates to left arm\nSweating, nauseous")
        with c2:
            st.markdown("**AMBER Example:**")
            st.code("45F, dysuria 3 days\nRight loin pain\nFever 38.2C")
        with c3:
            st.markdown("**GREEN Example:**")
            st.code("28M, runny nose 2 days\nMild sore throat\nNo fever")

    patient_description = st.text_area(
        "Enter patient symptoms and presentation:",
        height=150,
        placeholder="e.g. 45-year-old female, chest pain and shortness of breath for 2 hours...",
        key="patient_input",
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        triage_button = st.button(
            "Run Triage Assessment",
            type="primary",
            use_container_width=True,
        )

    if triage_button and patient_description:
        with st.spinner("Analysing patient presentation..."):
            try:
                t_start = time.time()
                result = st.session_state.rag_pipeline.triage_patient(patient_description)
                elapsed = round(time.time() - t_start, 2)
                st.session_state.triage_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "input": patient_description,
                    "result": result,
                    "override": None,
                    "response_time": elapsed,
                })
                st.session_state.audit_log.append({
                    "timestamp": datetime.now().isoformat(),
                    "patient_input": patient_description,
                    "triage_decision": result["triage_decision"],
                    "urgency": result["urgency_timeframe"],
                    "confidence": result["confidence"],
                    "red_flags": result["red_flags"],
                    "differentials": result.get("differentials", ""),
                    "response_time_seconds": elapsed,
                    "clinician_override": None,
                })
                st.session_state.last_result = len(st.session_state.triage_history) - 1
            except Exception as exc:
                st.error(f"Error during triage assessment: {exc}")
                with st.expander("Error details"):
                    st.exception(exc)
    elif triage_button:
        st.warning("Please enter a patient presentation before running triage.")

    if st.session_state.last_result is not None:
        case_idx = st.session_state.last_result
        if case_idx < len(st.session_state.triage_history):
            entry = st.session_state.triage_history[case_idx]
            st.markdown("---")
            st.header("Triage Result")
            show_result(entry["result"], entry["input"], case_idx)

    if st.session_state.triage_history:
        st.markdown("---")
        st.subheader(
            f"Triage History "
            f"(last {min(5, len(st.session_state.triage_history))} cases)"
        )
        for i, entry in enumerate(reversed(st.session_state.triage_history[-5:]), 1):
            if "result" not in entry:
                continue
            triage    = entry["result"]["triage_decision"]
            timestamp = entry["timestamp"][:19].replace("T", " ")
            override_tag = (
                f" | Override: {entry['override']['decision']}"
                if entry.get("override") else ""
            )
            with st.expander(
                f"Case {len(st.session_state.triage_history) - i + 1} "
                f"— {triage}{override_tag} — {timestamp}"
            ):
                hc1, hc2 = st.columns(2)
                with hc1:
                    st.text_area(
                        "Input", entry["input"],
                        height=100, disabled=True, key=f"hist_{i}",
                    )
                with hc2:
                    st.write(f"**AI Triage:** {entry['result']['triage_decision']}")
                    st.write(f"**Urgency:** {entry['result']['urgency_timeframe']}")
                    st.write(f"**Confidence:** {entry['result']['confidence']}")
                    if entry.get("override"):
                        st.error(
                            f"**Override:** {entry['override']['decision']} "
                            f"— {entry['override']['reason']}"
                        )
                st.write("**Reasoning:**")
                st.write(entry["result"]["clinical_reasoning"])
