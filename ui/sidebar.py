"""
ui/sidebar.py — Sidebar: demo scenarios, system info, session metrics, controls.
"""
import streamlit as st

import config

# Phase 4 — pre-loaded demo scenarios
DEMO_SCENARIOS: dict[str, str] = {
    "-- Select a demo scenario --": "",
    "RED — Acute chest pain (possible STEMI)": (
        "64-year-old male. Sudden onset crushing chest pain 45 minutes ago, "
        "radiating to left arm and jaw. Profuse sweating and nausea. No relief "
        "with rest. History of hypertension and hypercholesterolaemia. On aspirin 75mg."
    ),
    "RED — Stroke symptoms (FAST positive)": (
        "72-year-old female. Sudden onset right-sided facial droop and right arm "
        "weakness approximately 30 minutes ago. Slurred speech. No headache. "
        "History of atrial fibrillation, on warfarin. Last seen well 35 minutes ago."
    ),
    "RED — Paediatric non-blanching rash": (
        "8-year-old boy. High fever 39.8 degrees C for 12 hours. Mother noticed a "
        "non-blanching petechial rash on trunk and legs. Child is drowsy and very "
        "irritable. Neck stiffness reported. No recent travel or sick contacts."
    ),
    "AMBER — Febrile urinary tract infection": (
        "45-year-old female. Three-day history of dysuria and urinary frequency. "
        "Now developing right loin pain and fever of 38.2 degrees C with rigors. "
        "No vomiting. History of recurrent UTIs. Not pregnant. Urine dipstick positive."
    ),
    "GREEN — Upper respiratory tract infection": (
        "28-year-old male. Two-day history of runny nose, mild sore throat, and "
        "sneezing. No fever. No shortness of breath. Eating and drinking normally. "
        "No significant past medical history. Symptoms improving slightly."
    ),
}


def render_sidebar() -> None:
    """Render the full sidebar content."""
    with st.sidebar:
        # Phase 4 — Demo scenarios
        st.markdown("### Demo Scenarios")
        selected_demo = st.selectbox(
            "Load a pre-built scenario:",
            list(DEMO_SCENARIOS.keys()),
            key="demo_select",
        )
        if (
            st.button("Load Scenario")
            and selected_demo != "-- Select a demo scenario --"
        ):
            st.session_state["load_scenario"] = DEMO_SCENARIOS[selected_demo]
            st.rerun()

        st.markdown("---")
        st.markdown("### System Information")
        st.markdown(
            f"**Model:** {config.CHAT_MODEL}  \n"
            f"**Embeddings:** {config.EMBEDDING_MODEL}  \n"
            f"**Training Cases:** 447  \n"
            f"**Version:** 0.2.0 (POC)"
        )

        st.markdown("---")
        st.markdown("### How to Use")
        st.markdown(
            "1. Select a demo scenario or enter symptoms\n"
            "2. Click **Run Triage Assessment**\n"
            "3. Review the AI recommendation\n"
            "4. Check the explainability panel\n"
            "5. Override if needed (captured in audit)\n"
            "6. View metrics on the Dashboard tab"
        )

        st.markdown("---")
        st.markdown("### Session Metrics")
        if st.session_state.triage_history:
            total   = len(st.session_state.triage_history)
            red_c   = sum(
                1 for t in st.session_state.triage_history
                if t.get("result", {}).get("triage_decision") == "RED"
            )
            amber_c = sum(
                1 for t in st.session_state.triage_history
                if t.get("result", {}).get("triage_decision") == "AMBER"
            )
            green_c = sum(
                1 for t in st.session_state.triage_history
                if t.get("result", {}).get("triage_decision") == "GREEN"
            )
            overrides = sum(
                1 for t in st.session_state.triage_history if t.get("override")
            )
            st.metric("Total Triages", total)
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("RED",   red_c)
            sc2.metric("AMBER", amber_c)
            sc3.metric("GREEN", green_c)
            st.metric("Overrides", overrides)
        else:
            st.info("No triages yet this session.")

        st.markdown("---")
        st.warning("POC only — do not use with real patient data.")

        st.markdown("---")
        if st.button("Reset Session"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
        st.caption("GP Triage Assistant v0.2.0")
