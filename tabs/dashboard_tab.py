"""
tabs/dashboard_tab.py -- Executive Metrics Dashboard tab (Phases 3 & 5).
"""
import json

import pandas as pd
import streamlit as st

from src.database import get_dashboard_stats, get_all_triage_sessions

# Stage labels for pathway overview (mirrors pathway_tab.STAGE_LABELS)
_STAGE_LABELS = {
    1: "Presentation", 2: "Triage",    3: "Assignment", 4: "Referral",
    5: "Admission",    6: "Diagnosis", 7: "Treatment",  8: "Outcome",
    9: "Aftercare",   10: "Discharge",
}

# Phase 5 — baseline for time-saved calculation
MANUAL_TRIAGE_MINUTES = 15


def _audit_log_to_csv(audit_log: list) -> str:
    """Convert the session audit log list to a CSV string."""
    rows = []
    for entry in audit_log:
        override = entry.get("clinician_override") or {}
        rows.append({
            "Timestamp": entry.get("timestamp", ""),
            "AI Triage Decision": entry.get("triage_decision", ""),
            "Urgency": entry.get("urgency", ""),
            "Confidence": entry.get("confidence", ""),
            "Red Flags": entry.get("red_flags", ""),
            "Response Time (s)": entry.get("response_time_seconds", ""),
            "Override Decision": override.get("decision", ""),
            "Override Reason": override.get("reason", ""),
            "Override Detail": override.get("reason_detail", ""),
            "Override Timestamp": override.get("clinician_timestamp", ""),
        })
    return pd.DataFrame(rows).to_csv(index=False)


def _calc_session_stats(history: list) -> dict:
    """Compute aggregate stats dict from triage_history."""
    total = len(history)
    if total == 0:
        return {}
    red_c   = sum(1 for e in history if e["result"]["triage_decision"] == "RED")
    amber_c = sum(1 for e in history if e["result"]["triage_decision"] == "AMBER")
    green_c = sum(1 for e in history if e["result"]["triage_decision"] == "GREEN")
    overrides = sum(1 for e in history if e.get("override"))
    times = [e["response_time"] for e in history if e.get("response_time")]
    avg_time = sum(times) / len(times) if times else 0
    return {
        "total": total,
        "red": red_c,
        "amber": amber_c,
        "green": green_c,
        "overrides": overrides,
        "override_rate_pct": overrides / total * 100,
        "avg_response_s": avg_time,
    }


def _render_historical_section() -> None:
    """Render the all-time historical stats loaded from the SQLite database."""
    db_stats = get_dashboard_stats()
    if not db_stats or db_stats.get("total", 0) == 0:
        return

    st.markdown(
        '<div class="section-heading">All-Time Historical Records (Database)</div>',
        unsafe_allow_html=True,
    )

    total = db_stats["total"]
    h1, h2, h3, h4, h5, h6, h7 = st.columns(7)
    h1.metric("Total Patients",  db_stats.get("total_patients", 0))
    h2.metric("Total Triages",   total)
    h3.metric("RED",             db_stats["red"],
              delta=f"{db_stats['red']/total*100:.0f}%")
    h4.metric("AMBER",           db_stats["amber"],
              delta=f"{db_stats['amber']/total*100:.0f}%")
    h5.metric("GREEN",           db_stats["green"],
              delta=f"{db_stats['green']/total*100:.0f}%")
    h6.metric("Discharged",      db_stats.get("discharged", 0))
    h7.metric("Override Rate",   f"{db_stats['override_rate_pct']:.0f}%")

    # Historical triage log
    sessions = get_all_triage_sessions()
    if sessions:
        rows = []
        for s in sessions:
            rows.append({
                "Date":          (s["created_at"] or "")[:16].replace("T", " "),
                "NHS Number":    s["nhs_number"] or "—",
                "AI Triage":     s["triage_decision"],
                "Urgency":       s["urgency"] or "—",
                "Confidence":    s["confidence"] or "—",
                "Response (s)":  s.get("response_time_seconds") or "—",
                "Override":      s["clinician_override"] or "None",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    st.markdown("---")


def render_executive_dashboard() -> None:
    """Render the Executive Metrics Dashboard tab."""
    # Historical DB section always shown if data exists
    _render_historical_section()

    history = [e for e in st.session_state.triage_history if "result" in e]
    if not history:
        st.info(
            "No triage data yet in this session. Run cases on the Triage tab "
            "to populate the session metrics below."
        )
        return

    stats = _calc_session_stats(history)
    total    = stats["total"]
    avg_time = stats["avg_response_s"]
    time_saved_total_min = max(
        0, (MANUAL_TRIAGE_MINUTES * 60 - avg_time) * total
    ) / 60

    # ── KPI row ──────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="section-heading">Session KPIs</div>', unsafe_allow_html=True
    )
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total Triages", total)
    k2.metric("RED",   stats["red"],   delta=f"{stats['red']/total*100:.0f}%")
    k3.metric("AMBER", stats["amber"], delta=f"{stats['amber']/total*100:.0f}%")
    k4.metric("GREEN", stats["green"], delta=f"{stats['green']/total*100:.0f}%")
    k5.metric("Override Rate", f"{stats['override_rate_pct']:.0f}%")
    k6.metric("Avg Response", f"{avg_time:.1f}s")

    # ── Triage distribution + acuity trend ───────────────────────────────────
    st.markdown(
        '<div class="section-heading">Triage Distribution & Acuity Trend</div>',
        unsafe_allow_html=True,
    )
    ch1, ch2 = st.columns(2)

    with ch1:
        st.subheader("Case Distribution")
        dist_df = pd.DataFrame(
            {"Cases": [stats["red"], stats["amber"], stats["green"]]},
            index=["RED", "AMBER", "GREEN"],
        )
        st.bar_chart(dist_df)

    with ch2:
        st.subheader("Acuity Score Over Time")
        score_map = {"RED": 3, "AMBER": 2, "GREEN": 1}
        acuity_df = pd.DataFrame(
            [
                {"Case": i + 1, "Acuity": score_map.get(e["result"]["triage_decision"], 0)}
                for i, e in enumerate(history)
            ]
        ).set_index("Case")
        st.line_chart(acuity_df)
        st.caption("3 = RED (Emergency)  |  2 = AMBER (Urgent)  |  1 = GREEN (Routine)")

    # ── Override rate trend ───────────────────────────────────────────────────
    st.markdown(
        '<div class="section-heading">Override Rate Trend</div>',
        unsafe_allow_html=True,
    )
    running = 0
    trend_rows = []
    for i, e in enumerate(history):
        if e.get("override"):
            running += 1
        trend_rows.append({
            "Case": i + 1,
            "Override Rate (%)": running / (i + 1) * 100,
        })
    trend_df = pd.DataFrame(trend_rows).set_index("Case")
    st.line_chart(trend_df)
    st.caption(f"Final session override rate: {stats['override_rate_pct']:.1f}%")

    # ── Time-saved estimate ───────────────────────────────────────────────────
    st.markdown(
        '<div class="section-heading">Estimated Efficiency Gain</div>',
        unsafe_allow_html=True,
    )
    t1, t2, t3 = st.columns(3)
    t1.metric("AI Avg Response", f"{avg_time:.1f}s")
    t2.metric("Manual Baseline (est.)", f"{MANUAL_TRIAGE_MINUTES} min")
    t3.metric("Cumulative Time Saved", f"{time_saved_total_min:.0f} min")
    st.caption(
        f"Based on {total} case(s). Manual baseline of {MANUAL_TRIAGE_MINUTES} minutes "
        f"represents estimated GP administrative triage documentation time. "
        f"AI augments — it does not replace — clinical assessment."
    )

    # ── Phase 3: Audit log summary + download ────────────────────────────────
    st.markdown(
        '<div class="section-heading">Audit Log</div>', unsafe_allow_html=True
    )

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Total Cases", total)
    a2.metric("Override Rate", f"{stats['override_rate_pct']:.1f}%")
    a3.metric("RED Cases", f"{stats['red']} ({stats['red']/total*100:.0f}%)")
    a4.metric("GREEN Cases", f"{stats['green']} ({stats['green']/total*100:.0f}%)")

    rows = []
    for i, e in enumerate(history):
        override = e.get("override") or {}
        rows.append({
            "Case": i + 1,
            "Time": e["timestamp"][:16].replace("T", " "),
            "AI Triage": e["result"]["triage_decision"],
            "Urgency": e["result"]["urgency_timeframe"],
            "Confidence": e["result"]["confidence"],
            "Response (s)": e.get("response_time", ""),
            "Override": override.get("decision", "None"),
            "Override Reason": override.get("reason", ""),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    st.markdown("---")
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "Download Audit Log (JSON)",
            data=json.dumps(st.session_state.audit_log, indent=2),
            file_name="gp_triage_audit_log.json",
            mime="application/json",
        )
    with dl2:
        if st.session_state.audit_log:
            st.download_button(
                "Download Audit Log (CSV)",
                data=_audit_log_to_csv(st.session_state.audit_log),
                file_name="gp_triage_audit_log.csv",
                mime="text/csv",
            )

    # ── Pathway Overview ──────────────────────────────────────────────────────
    pathways = st.session_state.get("pathways", {})
    if not pathways:
        return

    st.markdown(
        '<div class="section-heading">Patient Pathway Overview</div>',
        unsafe_allow_html=True,
    )

    # KPI row
    total_p    = len(pathways)
    discharged = sum(
        1 for p in pathways.values()
        if p["stages"].get(10, {}).get("status") == "complete"
    )
    stage_counts: dict[int, int] = {}
    for p in pathways.values():
        c = p["current_stage"]
        stage_counts[c] = stage_counts.get(c, 0) + 1
    bottleneck = max(stage_counts, key=stage_counts.get) if stage_counts else None

    pk1, pk2, pk3, pk4 = st.columns(4)
    pk1.metric("Active Pathways",  total_p)
    pk2.metric("Discharged",       discharged)
    pk3.metric("Discharge Rate",   f"{discharged / total_p * 100:.0f}%" if total_p else "0%")
    pk4.metric(
        "Bottleneck Stage",
        f"Stage {bottleneck}: {_STAGE_LABELS.get(bottleneck, 'N/A')}"
        if bottleneck else "—",
    )

    # Per-pathway table
    rows = []
    for nhs, p in pathways.items():
        completed = sum(1 for s in p["stages"].values() if s.get("status") == "complete")
        s6_data   = p["stages"].get(6, {}).get("data", {})
        rows.append({
            "NHS Number":     nhs,
            "Current Stage":  f"{p['current_stage']} — {_STAGE_LABELS.get(p['current_stage'], 'Discharge')}",
            "Stages Complete": f"{completed}/10",
            "Diagnosis":      s6_data.get("confirmed_diagnosis", "—"),
            "Discharged":     "Yes" if p["stages"].get(10, {}).get("status") == "complete" else "No",
            "Created":        p["created_at"][:16].replace("T", " "),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    # Stage distribution bar chart
    if len(pathways) > 1:
        st.subheader("Pathway Stage Distribution")
        dist_data = {
            _STAGE_LABELS.get(s, f"Stage {s}"): cnt
            for s, cnt in sorted(stage_counts.items())
        }
        stage_df = pd.DataFrame(
            {"Patients": list(dist_data.values())},
            index=list(dist_data.keys()),
        )
        st.bar_chart(stage_df)
