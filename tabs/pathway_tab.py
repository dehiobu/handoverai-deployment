"""
tabs/pathway_tab.py — 10-stage Patient Pathway Tracker.

Stages 1-4 auto-populate from Triage tab session data.
Stages 5-10 are manually entered (demo / simulation).
"""
import json
from datetime import date, datetime

import streamlit as st

from src import letter_generator
from src.database import (
    save_patient, save_pathway_stage,
    save_ward_log, get_ward_logs,
    save_observation, get_observations,
    save_medication, get_medications,
    save_safeguarding_flag, get_safeguarding_flags,
    update_discharge_checklist, get_discharge_checklist,
    get_patient_timeline, get_patient,
)


def _fmt_dt(dt, chars: int = 16) -> str:
    """Safely format a datetime, date, or string value to a fixed-length string.

    Handles the case where SQLite returns Python datetime objects instead of
    strings (depends on connection detect_types setting).
    """
    if dt is None:
        return ""
    if isinstance(dt, (datetime, date)):
        s = dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        s = str(dt)
    return s[:chars]


# ── Constants ──────────────────────────────────────────────────────────────────

STAGE_LABELS = {
    1: "Presentation", 2: "Triage",    3: "Assignment", 4: "Referral",
    5: "Admission",    6: "Diagnosis", 7: "Treatment",  8: "Outcome",
    9: "Aftercare",   10: "Discharge",
}

_DOCTORS = [
    {"name": "Dr. D. Ehiobu",     "role": "GP",                    "site": "Holmhurst Medical Centre"},
    {"name": "Dr. D. Wake-Trent", "role": "Cardiologist",           "site": "East Surrey Hospital"},
    {"name": "Dr. A. Patel",      "role": "Paediatrician",          "site": "East Surrey Hospital"},
    {"name": "Dr. S. Morrison",   "role": "GP",                     "site": "Greystone House Surgery"},
    {"name": "Dr. R. Chen",       "role": "Respiratory Consultant", "site": "East Surrey Hospital"},
    {"name": "Dr. L. Okafor",     "role": "Ophthalmologist",        "site": "London Eye Hospital"},
]
_DOCTOR_NAMES = [f"{d['name']} — {d['role']}" for d in _DOCTORS]

_ADMISSION_TYPES   = ["Emergency", "Elective", "Day Case"]
_TREATMENT_TYPES   = ["Medical", "Surgical", "Conservative", "Observation"]
_ANAESTHETIC_TYPES = ["General", "Local", "None", "TBD"]
_DISCHARGE_TYPES   = ["Home", "Transfer", "Self-discharge", "Deceased"]
_COMMUNITY_REFS    = [
    "District Nurse", "Physiotherapy", "Occupational Therapy",
    "Mental Health", "Social Services", "Community Nursing",
]
_OUTCOME_TYPES = ["Successful", "Complications", "Ongoing", "Deceased"]


# ── Pathway factory ────────────────────────────────────────────────────────────

def _make_new_pathway(nhs_number: str, triage_case_idx: int | None = None) -> dict:
    """Return a fresh pathway dict, auto-filling stages 1-4 from triage history."""
    now    = datetime.now().isoformat()
    stages = {i: {"status": "pending", "timestamp": None, "data": {}} for i in range(1, 11)}
    current_stage = 1

    if triage_case_idx is not None:
        history = st.session_state.get("triage_history", [])
        if triage_case_idx < len(history):
            entry  = history[triage_case_idx]
            result = entry["result"]

            # Stage 1 — Presentation
            stages[1] = {
                "status": "complete", "timestamp": entry["timestamp"],
                "data": {
                    "patient_description": entry["input"],
                    "presentation_time":   entry["timestamp"],
                },
            }
            current_stage = 2

            # Stage 2 — Triage
            stages[2] = {
                "status": "complete", "timestamp": entry["timestamp"],
                "data": {
                    "ai_decision":        result["triage_decision"],
                    "urgency":            result["urgency_timeframe"],
                    "confidence":         result["confidence"],
                    "response_time_s":    entry.get("response_time"),
                    "clinician_override": entry.get("override"),
                },
            }
            current_stage = 3

            # Stage 3 — Assignment (if doctor assigned in Triage tab)
            doc  = st.session_state.get(f"selected_doctor_obj_{triage_case_idx}")
            spec = st.session_state.get(f"specialty_{triage_case_idx}", "General Practice")
            if doc:
                stages[3] = {
                    "status": "complete", "timestamp": now,
                    "data": {
                        "assigned_doctor": doc["name"],
                        "specialty":       spec,
                        "site":            doc["site"],
                    },
                }
                current_stage = 4

            # Stage 4 — Referral (if imaging/bloods selected in Triage tab)
            imaging = st.session_state.get(f"imaging_{triage_case_idx}", [])
            bloods  = st.session_state.get(f"bloods_{triage_case_idx}", [])
            if imaging or bloods:
                stages[4] = {
                    "status": "complete", "timestamp": now,
                    "data": {
                        "imaging":          imaging,
                        "blood_tests":      bloods,
                        "letter_generated": f"referral_letter_{triage_case_idx}" in st.session_state,
                    },
                }
                current_stage = 5

    return {
        "nhs_number":       nhs_number,
        "created_at":       now,
        "triage_case_idx":  triage_case_idx,
        "current_stage":    current_stage,
        "stages":           stages,
    }


# ── Visual stepper ─────────────────────────────────────────────────────────────

def _render_stepper(stages: dict, current_stage: int) -> None:
    """Render NHS-styled horizontal 10-stage progress bar."""
    circles = []
    for i in range(1, 11):
        status = stages.get(i, {}).get("status", "pending")
        if status == "complete":
            bg, fg, icon  = "#009639", "#ffffff", "✓"
            label_col     = "#009639"
        elif i == current_stage:
            bg, fg, icon  = "#005EB8", "#ffffff", str(i)
            label_col     = "#005EB8"
        else:
            bg, fg, icon  = "#AEB7BD", "#ffffff", str(i)
            label_col     = "#6B7280"

        circles.append(
            f'<div style="text-align:center;flex:0 0 auto;">'
            f'<div style="width:34px;height:34px;border-radius:50%;background:{bg};'
            f'color:{fg};display:flex;align-items:center;justify-content:center;'
            f'font-weight:700;font-size:0.88rem;margin:0 auto;">{icon}</div>'
            f'<div style="font-size:0.65rem;color:{label_col};font-weight:600;'
            f'margin-top:4px;max-width:58px;line-height:1.2;">'
            f'{STAGE_LABELS[i]}</div></div>'
        )

    parts = []
    for idx, circle in enumerate(circles):
        parts.append(circle)
        if idx < len(circles) - 1:
            left_done  = stages.get(idx + 1, {}).get("status") == "complete"
            conn_color = "#009639" if left_done else "#D1D5DB"
            parts.append(
                f'<div style="flex:1;height:2px;background:{conn_color};'
                f'min-width:8px;align-self:center;margin-bottom:20px;"></div>'
            )

    html = (
        '<div style="display:flex;align-items:flex-start;gap:2px;'
        'padding:16px;background:#F0F4F5;border-radius:8px;'
        'border:1px solid #AEB7BD;margin-bottom:16px;overflow-x:auto;">'
        + "".join(parts)
        + "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ── Stage header badge ─────────────────────────────────────────────────────────

def _stage_header(num: int, status: str, timestamp: str | None) -> None:
    color = {"complete": "#009639", "in_progress": "#005EB8"}.get(status, "#AEB7BD")
    ts    = f" — {_fmt_dt(timestamp, 16).replace('T', ' ')}" if timestamp else ""
    st.markdown(
        f'<div style="background:{color};color:#fff;padding:8px 16px;'
        f'border-radius:6px;font-weight:700;font-size:1rem;margin-bottom:8px;">'
        f'Stage {num} — {STAGE_LABELS[num]}'
        f'<span style="font-size:0.8rem;opacity:0.85;"> [{status.upper()}]{ts}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Read-only completed stage display ─────────────────────────────────────────

def _show_readonly(stage_data: dict) -> None:
    data = stage_data.get("data", {})
    if not data:
        st.caption("No data recorded.")
        return
    for k, v in data.items():
        if v is None or v == "" or v == []:
            continue
        label = k.replace("_", " ").title()
        if isinstance(v, list):
            st.markdown(f"**{label}:** {', '.join(str(x) for x in v)}")
        elif isinstance(v, dict):
            st.markdown(f"**{label}:** {v}")
        else:
            st.markdown(f"**{label}:** {v}")


# ── Stage 5 — Admission ────────────────────────────────────────────────────────

def _render_stage_5(pathway: dict, pkey: str) -> None:
    st.caption(
        "Demo simulation — in production this integrates with EPR/PAS system"
    )
    with st.form(key=f"s5_{pkey}"):
        c1, c2 = st.columns(2)
        with c1:
            admission_date = st.date_input("Admission Date", value=date.today())
            ward_name      = st.text_input("Ward Name", placeholder="e.g. Victoria Ward")
            bed_number     = st.text_input("Bed Number", placeholder="e.g. 14B")
        with c2:
            admitting_cons = st.selectbox("Admitting Consultant", _DOCTOR_NAMES)
            admission_type = st.selectbox("Admission Type", _ADMISSION_TYPES)
            hospital       = st.text_input("NHS Hospital", value="East Surrey Hospital")
        adm_status = st.selectbox("Admission Status", ["Pending", "Admitted", "Transferred"])
        submitted  = st.form_submit_button("Save Stage 5 — Admission", type="primary")

    if submitted:
        stage_data_5 = {
            "admission_date":       str(admission_date),
            "ward_name":            ward_name,
            "bed_number":           bed_number,
            "admitting_consultant": admitting_cons,
            "admission_type":       admission_type,
            "hospital":             hospital,
            "admission_status":     adm_status,
        }
        pathway["stages"][5] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data_5,
        }
        save_pathway_stage(
            pathway["nhs_number"], 5, STAGE_LABELS[5], "complete", stage_data_5
        )
        if pathway["current_stage"] <= 5:
            pathway["current_stage"] = 6
        st.rerun()


# ── Stage 6 — Diagnosis ────────────────────────────────────────────────────────

def _render_stage_6(pathway: dict, pkey: str) -> None:
    st.caption(
        "Demo simulation — in production this integrates with EPR/PAS system"
    )
    with st.form(key=f"s6_{pkey}"):
        confirmed_dx = st.text_input(
            "Confirmed Diagnosis", placeholder="e.g. Acute Myocardial Infarction"
        )
        c1, c2 = st.columns(2)
        with c1:
            icd10  = st.text_input("ICD-10 Code",    placeholder="e.g. I21.0 — Acute MI")
            snomed = st.text_input("SNOMED CT Code", placeholder="e.g. 57054005")
        with c2:
            dx_cons = st.selectbox("Diagnosing Consultant", _DOCTOR_NAMES)
            dx_date = st.date_input("Diagnosis Date", value=date.today())
        dx_status = st.selectbox("Status", ["Pending", "Confirmed", "Revised"])
        submitted = st.form_submit_button("Save Stage 6 — Diagnosis", type="primary")

    if submitted:
        stage_data_6 = {
            "confirmed_diagnosis":   confirmed_dx,
            "icd10_code":            icd10,
            "snomed_code":           snomed,
            "diagnosing_consultant": dx_cons,
            "diagnosis_date":        str(dx_date),
            "diagnosis_status":      dx_status,
        }
        pathway["stages"][6] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data_6,
        }
        save_pathway_stage(
            pathway["nhs_number"], 6, STAGE_LABELS[6], "complete", stage_data_6
        )
        if pathway["current_stage"] <= 6:
            pathway["current_stage"] = 7
        st.rerun()


# ── Stage 7 — Treatment ────────────────────────────────────────────────────────

def _render_stage_7(pathway: dict, pkey: str) -> None:
    st.caption(
        "Demo simulation — in production this integrates with EPR/PAS system"
    )
    with st.form(key=f"s7_{pkey}"):
        c1, c2 = st.columns(2)
        with c1:
            treatment_type = st.selectbox("Treatment Type", _TREATMENT_TYPES)
            procedure_name = st.text_input(
                "Procedure Name", placeholder="e.g. Flexible cystoscopy"
            )
            theatre        = st.text_input(
                "Theatre / Location", placeholder="e.g. Theatre 3, Main Block"
            )
        with c2:
            anaesthetic = st.selectbox("Anaesthetic Type", _ANAESTHETIC_TYPES)
            surgeon     = st.selectbox("Operating Surgeon", _DOCTOR_NAMES)
            proc_date   = st.date_input("Procedure Date", value=date.today())
        duration  = st.number_input("Duration (minutes)", min_value=0, value=0, step=5)
        tx_status = st.selectbox("Status", ["Planned", "In Progress", "Complete", "Cancelled"])
        submitted = st.form_submit_button("Save Stage 7 — Treatment", type="primary")

    if submitted:
        stage_data_7 = {
            "treatment_type":    treatment_type,
            "procedure_name":    procedure_name,
            "theatre":           theatre,
            "anaesthetic_type":  anaesthetic,
            "operating_surgeon": surgeon,
            "procedure_date":    str(proc_date),
            "duration_minutes":  duration,
            "treatment_status":  tx_status,
        }
        pathway["stages"][7] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data_7,
        }
        save_pathway_stage(
            pathway["nhs_number"], 7, STAGE_LABELS[7], "complete", stage_data_7
        )
        if pathway["current_stage"] <= 7:
            pathway["current_stage"] = 8
        st.rerun()


# ── Stage 8 — Outcome ──────────────────────────────────────────────────────────

def _render_stage_8(pathway: dict, pkey: str) -> None:
    admit_date_str = pathway["stages"].get(5, {}).get("data", {}).get("admission_date", "")
    st.caption(
        "Demo simulation — in production this integrates with EPR/PAS system"
    )
    with st.form(key=f"s8_{pkey}"):
        outcome       = st.selectbox("Outcome", _OUTCOME_TYPES)
        complications = st.text_area(
            "Complications (leave blank if none)", height=80
        )
        follow_up     = st.radio("Follow-up Required", ["Yes", "No"], horizontal=True)
        outcome_notes = st.text_area("Outcome Notes", height=80)
        oc_status     = st.selectbox("Status", ["Pending", "Recorded"])
        submitted     = st.form_submit_button("Save Stage 8 — Outcome", type="primary")

    if submitted:
        los = "N/A"
        if admit_date_str:
            try:
                admit = date.fromisoformat(admit_date_str)
                los   = f"{(date.today() - admit).days} days"
            except ValueError:
                pass
        stage_data_8 = {
            "outcome":            outcome,
            "complications":      complications or "None",
            "length_of_stay":     los,
            "follow_up_required": follow_up,
            "outcome_notes":      outcome_notes,
            "outcome_status":     oc_status,
        }
        pathway["stages"][8] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data_8,
        }
        save_pathway_stage(
            pathway["nhs_number"], 8, STAGE_LABELS[8], "complete", stage_data_8
        )
        if pathway["current_stage"] <= 8:
            pathway["current_stage"] = 9
        st.rerun()


# ── Stage 9 — Aftercare ────────────────────────────────────────────────────────

def _render_stage_9(pathway: dict, pkey: str) -> None:
    st.caption(
        "Demo simulation — in production this integrates with EPR/PAS system"
    )
    with st.form(key=f"s9_{pkey}"):
        c1, c2 = st.columns(2)
        with c1:
            followup_date   = st.date_input("Follow-up Appointment Date")
            followup_loc    = st.text_input(
                "Follow-up Location", placeholder="e.g. Holmhurst Medical Centre"
            )
            followup_doctor = st.selectbox("Follow-up Doctor", _DOCTOR_NAMES)
        with c2:
            medications  = st.text_area(
                "Medications Prescribed", height=80,
                placeholder="e.g. Aspirin 75mg OD, Atorvastatin 40mg OD",
            )
            instructions = st.text_area(
                "Aftercare Instructions", height=80,
                placeholder="e.g. Rest for 1 week, avoid strenuous activity",
            )
        community_refs = st.multiselect("Community Referrals", _COMMUNITY_REFS)
        ac_status      = st.selectbox("Status", ["Planned", "In Progress", "Complete"])
        submitted      = st.form_submit_button("Save Stage 9 — Aftercare", type="primary")

    if submitted:
        stage_data_9 = {
            "followup_date":          str(followup_date),
            "followup_location":      followup_loc,
            "followup_doctor":        followup_doctor,
            "medications":            medications,
            "aftercare_instructions": instructions,
            "community_referrals":    community_refs,
            "aftercare_status":       ac_status,
        }
        pathway["stages"][9] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data_9,
        }
        save_pathway_stage(
            pathway["nhs_number"], 9, STAGE_LABELS[9], "complete", stage_data_9
        )
        if pathway["current_stage"] <= 9:
            pathway["current_stage"] = 10
        st.rerun()


# ── Stage 10 — Discharge ───────────────────────────────────────────────────────

def _render_stage_10(pathway: dict, pkey: str) -> None:
    # Pre-discharge checklist — must complete required items before saving
    checklist_ready = _render_discharge_checklist_section(pathway, pkey)

    st.caption(
        "Demo simulation — in production this integrates with EPR/PAS system"
    )
    with st.form(key=f"s10_{pkey}"):
        c1, c2 = st.columns(2)
        with c1:
            discharge_date = st.date_input("Discharge Date", value=date.today())
            discharge_type = st.selectbox("Discharge Type", _DISCHARGE_TYPES)
            gp_notified    = st.checkbox("GP Notification sent")
            gp_letter      = st.checkbox("GP Letter generated")
        with c2:
            accompanied   = st.checkbox("Patient accompanied on discharge")
            transport     = st.checkbox("Transport arranged")
            discharge_meds = st.text_area(
                "Discharge Medications", height=80,
                placeholder="e.g. Aspirin 75mg OD x 30 days",
            )
        discharge_summary = st.text_area(
            "Discharge Summary", height=120,
            placeholder="Brief clinical summary for GP records...",
        )
        dc_status = st.selectbox("Status", ["Pending", "Discharged"])
        submitted = st.form_submit_button(
            "Save Stage 10 — Discharge", type="primary",
            disabled=not checklist_ready,
        )

    if submitted and not checklist_ready:
        st.warning("Complete all required checklist items before saving discharge.")
    elif submitted:
        stage_data_10 = {
            "discharge_date":        str(discharge_date),
            "discharge_type":        discharge_type,
            "discharge_summary":     discharge_summary,
            "gp_notified":           gp_notified,
            "gp_letter_generated":   gp_letter,
            "patient_accompanied":   accompanied,
            "transport_arranged":    transport,
            "discharge_medications": discharge_meds,
            "discharge_status":      dc_status,
        }
        pathway["stages"][10] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data_10,
        }
        save_pathway_stage(
            pathway["nhs_number"], 10, STAGE_LABELS[10], "complete", stage_data_10
        )
        # Stage 10 is the terminus -- keep current_stage at 10
        pathway["current_stage"] = 10
        st.success("Patient pathway complete!")
        st.rerun()


# ── Stage dispatcher ───────────────────────────────────────────────────────────

_STAGE_RENDERERS = {
    5:  _render_stage_5,
    6:  _render_stage_6,
    7:  _render_stage_7,
    8:  _render_stage_8,
    9:  _render_stage_9,
    10: _render_stage_10,
}


# ── NEWS2 scoring ─────────────────────────────────────────────────────────────

def _calc_news2(temp: float, resp_rate: int, o2_sats: int,
                sys_bp: int, hr: int, avpu: str) -> int:
    """Calculate National Early Warning Score 2 (NEWS2)."""
    score = 0
    # Temperature
    if temp <= 35.0:      score += 3
    elif temp <= 36.0:    score += 1
    elif temp <= 38.0:    score += 0
    elif temp <= 39.0:    score += 1
    else:                 score += 2
    # Respiratory rate
    if resp_rate <= 8:    score += 3
    elif resp_rate <= 11: score += 1
    elif resp_rate <= 20: score += 0
    elif resp_rate <= 24: score += 2
    else:                 score += 3
    # SpO2 (Scale 1 — no supplemental O2 assumed)
    if o2_sats <= 91:    score += 3
    elif o2_sats <= 93:  score += 2
    elif o2_sats <= 95:  score += 1
    # Systolic BP
    if sys_bp <= 90:     score += 3
    elif sys_bp <= 100:  score += 2
    elif sys_bp <= 110:  score += 1
    elif sys_bp <= 219:  score += 0
    else:                score += 3
    # Heart rate
    if hr <= 40:         score += 3
    elif hr <= 50:       score += 1
    elif hr <= 90:       score += 0
    elif hr <= 110:      score += 1
    elif hr <= 130:      score += 2
    else:                score += 3
    # AVPU — any deviation from Alert = 3
    if avpu != "Alert":  score += 3
    return score


# ── Feature 1 — Ward Daily Log ────────────────────────────────────────────────

_SHIFTS = ["Morning Round", "Afternoon Review", "Night Review"]
_CLINICIAN_ROLES = ["Consultant", "Registrar", "SHO", "Nurse", "Other"]


def _render_ward_log(pathway: dict, pkey: str) -> None:
    """Ward daily SOAP log section."""
    nhs = pathway["nhs_number"]
    st.markdown(
        '<div class="section-heading">Ward Daily Log (SOAP)</div>',
        unsafe_allow_html=True,
    )
    st.caption("Record clinical assessment for each ward round shift.")

    with st.form(key=f"ward_log_form_{pkey}"):
        c1, c2, c3 = st.columns(3)
        with c1:
            log_date = st.date_input("Date", key=f"wl_date_{pkey}")
            shift    = st.selectbox("Shift", _SHIFTS, key=f"wl_shift_{pkey}")
        with c2:
            clinician_preset = st.selectbox(
                "Clinician", [d["name"] for d in _DOCTORS] + ["Other (free text)"],
                key=f"wl_clin_preset_{pkey}",
            )
            clinician_free = st.text_input(
                "Clinician name (if Other)", key=f"wl_clin_free_{pkey}"
            )
        with c3:
            role = st.selectbox("Role", _CLINICIAN_ROLES, key=f"wl_role_{pkey}")

        st.markdown("**SOAP Note**")
        subjective  = st.text_area("S — Subjective (patient reports)", height=70,
                                    key=f"wl_s_{pkey}")
        objective   = st.text_area("O — Objective (clinical findings)", height=70,
                                    key=f"wl_o_{pkey}")
        assessment  = st.text_area("A — Assessment (clinical impression)", height=70,
                                    key=f"wl_a_{pkey}")
        plan        = st.text_area("P — Plan (treatment plan)", height=70,
                                    key=f"wl_p_{pkey}")
        submitted   = st.form_submit_button("Add to Log", type="primary")

    if submitted:
        clinician = (
            clinician_free.strip()
            if clinician_preset == "Other (free text)" and clinician_free.strip()
            else clinician_preset
        )
        if not clinician or not subjective.strip():
            st.warning("Clinician name and Subjective (S) are required.")
        else:
            save_ward_log(nhs, str(log_date), shift, clinician, role,
                          subjective, objective, assessment, plan)
            st.success("Ward log entry saved.")
            st.rerun()

    logs = get_ward_logs(nhs)
    if logs:
        st.markdown(f"**{len(logs)} log entries** (newest first):")
        for entry in logs:
            ts = _fmt_dt(entry.get("created_at"), 16).replace("T", " ")
            with st.expander(
                f"{ts} | {entry['shift']} | {entry['clinician']} ({entry['role']})"
            ):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**S:** {entry['subjective']}")
                    st.markdown(f"**O:** {entry['objective']}")
                with c2:
                    st.markdown(f"**A:** {entry['assessment']}")
                    st.markdown(f"**P:** {entry['plan']}")
    else:
        st.info("No ward log entries yet.")


# ── Feature 2 — Nurse Observations (NEWS2) ───────────────────────────────────

_AVPU_OPTIONS = ["Alert", "Voice", "Pain", "Unresponsive"]
_WOUND_OPTIONS = ["Intact", "Changed", "Escalated"]
_PRESSURE_OPTIONS = ["Normal", "At risk", "Dressing applied"]


def _render_observations(pathway: dict, pkey: str) -> None:
    """Nurse observations + auto-calculated NEWS2 score."""
    nhs = pathway["nhs_number"]
    st.markdown(
        '<div class="section-heading">Nurse Observations (NEWS2)</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Record per-shift observations. NEWS2 score calculated automatically. "
        "Normal ranges shown in parentheses."
    )

    with st.form(key=f"obs_form_{pkey}"):
        c1, c2 = st.columns(2)
        with c1:
            obs_date  = st.date_input("Date", key=f"obs_date_{pkey}")
            obs_time  = st.time_input("Time", key=f"obs_time_{pkey}")
            nurse_name = st.text_input("Nurse Name", key=f"obs_nurse_{pkey}")
            shift      = st.selectbox("Shift", ["Morning", "Afternoon", "Night"],
                                      key=f"obs_shift_{pkey}")
        with c2:
            st.markdown("**Vital Signs**")
            temp      = st.number_input("Temperature °C (36.1–37.2)",
                                         min_value=30.0, max_value=43.0, value=37.0,
                                         step=0.1, key=f"obs_temp_{pkey}")
            bp_sys    = st.number_input("Systolic BP mmHg (>100)",
                                         min_value=50, max_value=300, value=120,
                                         key=f"obs_bpsys_{pkey}")
            bp_dia    = st.number_input("Diastolic BP mmHg",
                                         min_value=30, max_value=200, value=80,
                                         key=f"obs_bpdia_{pkey}")
            hr        = st.number_input("Heart Rate bpm (51–90)",
                                         min_value=20, max_value=250, value=80,
                                         key=f"obs_hr_{pkey}")
            rr        = st.number_input("Respiratory Rate /min (12–20)",
                                         min_value=4, max_value=60, value=16,
                                         key=f"obs_rr_{pkey}")
            spo2      = st.number_input("SpO2 % (>=96)",
                                         min_value=60, max_value=100, value=98,
                                         key=f"obs_spo2_{pkey}")
            avpu      = st.selectbox("AVPU", _AVPU_OPTIONS, key=f"obs_avpu_{pkey}")
            pain      = st.slider("Pain Score (0–10)", 0, 10, 0,
                                   key=f"obs_pain_{pkey}")

        st.markdown("**Fluid Balance**")
        fb1, fb2 = st.columns(2)
        with fb1:
            fluid_in  = st.number_input("Input (ml) — IV + oral", min_value=0,
                                         value=0, step=50, key=f"obs_flin_{pkey}")
        with fb2:
            fluid_out = st.number_input("Output (ml) — urine + drains", min_value=0,
                                         value=0, step=50, key=f"obs_flout_{pkey}")

        wc1, wc2 = st.columns(2)
        with wc1:
            wound_check = st.selectbox("Wound/Dressing", _WOUND_OPTIONS,
                                        key=f"obs_wound_{pkey}")
        with wc2:
            pressure    = st.selectbox("Pressure Areas", _PRESSURE_OPTIONS,
                                        key=f"obs_pressure_{pkey}")

        submitted = st.form_submit_button("Save Observations", type="primary")

    if submitted:
        if not nurse_name.strip():
            st.warning("Nurse name is required.")
        else:
            news2 = _calc_news2(temp, int(rr), int(spo2), int(bp_sys), int(hr), avpu)
            obs_dt = f"{obs_date} {obs_time}"
            save_observation(
                nhs, obs_dt, shift, nurse_name.strip(),
                temp, int(bp_sys), int(bp_dia), int(hr), int(rr), int(spo2),
                avpu, pain, int(fluid_in), int(fluid_out),
                wound_check, pressure, news2,
            )
            if news2 >= 7:
                st.error(
                    f"NEWS2 = {news2} — URGENT MEDICAL REVIEW REQUIRED. "
                    "Escalate to senior clinician immediately."
                )
            elif news2 >= 5:
                st.warning(f"NEWS2 = {news2} — Increased monitoring required.")
            else:
                st.success(f"NEWS2 = {news2} — Routine monitoring.")
            st.rerun()

    obs_list = get_observations(nhs)
    if obs_list:
        import pandas as pd

        def _news2_badge(score: int) -> str:
            if score >= 7:  return f"RED ({score})"
            if score >= 5:  return f"AMBER ({score})"
            return f"GREEN ({score})"

        rows = []
        for o in obs_list:
            rows.append({
                "Date/Time":  _fmt_dt(o.get("obs_date"), 16),
                "Shift":      o["shift"],
                "Nurse":      o["nurse_name"],
                "Temp":       o["temperature"],
                "BP":         f"{o['bp_systolic']}/{o['bp_diastolic']}",
                "HR":         o["heart_rate"],
                "RR":         o["respiratory_rate"],
                "SpO2%":      o["o2_sats"],
                "AVPU":       o["avpu"],
                "Pain":       o["pain_score"],
                "NEWS2":      _news2_badge(o["news2_score"] or 0),
                "Fluid In":   o["fluid_input"],
                "Fluid Out":  o["fluid_output"],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

        # Alert for any current RED NEWS2
        latest_news2 = obs_list[0]["news2_score"] or 0
        if latest_news2 >= 7:
            st.error(
                f"LATEST NEWS2 = {latest_news2} — URGENT: Patient requires "
                "immediate senior review."
            )
    else:
        st.info("No observations recorded yet.")


# ── Feature 3 — Medication Administration Record (MAR) ───────────────────────

_ROUTES      = ["Oral", "IV", "IM", "SC", "Topical", "Inhaled", "Other"]
_FREQUENCIES = ["OD", "BD", "TDS", "QDS", "PRN", "Stat", "Other"]
_MED_STATUSES = ["Given", "Withheld", "Refused", "Not available"]


def _render_medications(pathway: dict, pkey: str) -> None:
    """Medication Administration Record (MAR)."""
    nhs = pathway["nhs_number"]
    st.markdown(
        '<div class="section-heading">Medication Administration Record (MAR)</div>',
        unsafe_allow_html=True,
    )

    with st.form(key=f"mar_form_{pkey}"):
        c1, c2, c3 = st.columns(3)
        with c1:
            med_date      = st.date_input("Date", key=f"mar_date_{pkey}")
            med_time      = st.time_input("Time", key=f"mar_time_{pkey}")
            drug_name     = st.text_input("Drug Name", key=f"mar_drug_{pkey}",
                                           placeholder="e.g. Aspirin")
            dose          = st.text_input("Dose", key=f"mar_dose_{pkey}",
                                           placeholder="e.g. 75mg")
        with c2:
            route         = st.selectbox("Route", _ROUTES, key=f"mar_route_{pkey}")
            frequency     = st.selectbox("Frequency", _FREQUENCIES, key=f"mar_freq_{pkey}")
            prescribed_by = st.selectbox(
                "Prescribed By", [d["name"] for d in _DOCTORS],
                key=f"mar_prescriber_{pkey}",
            )
        with c3:
            admin_by  = st.text_input("Administered By (nurse)", key=f"mar_admin_{pkey}")
            status    = st.selectbox("Status", _MED_STATUSES, key=f"mar_status_{pkey}")
            notes     = st.text_input("Notes (optional)", key=f"mar_notes_{pkey}")
        submitted = st.form_submit_button("Add to MAR", type="primary")

    if submitted:
        if not drug_name.strip():
            st.warning("Drug name is required.")
        else:
            save_medication(
                nhs, f"{med_date} {med_time}", drug_name.strip(),
                dose, route, frequency, prescribed_by,
                admin_by.strip(), status, notes.strip(),
            )
            st.success(f"Medication added: {drug_name} {dose}")
            st.rerun()

    meds = get_medications(nhs)
    if meds:
        import pandas as pd
        rows = []
        for m in meds:
            rows.append({
                "Date/Time":    _fmt_dt(m.get("med_date"), 16),
                "Drug":         m["drug_name"],
                "Dose":         m["dose"],
                "Route":        m["route"],
                "Freq":         m["frequency"],
                "Prescribed By": m["prescribed_by"],
                "Given By":     m["administered_by"],
                "Status":       m["status"],
                "Notes":        m.get("notes", ""),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    else:
        st.info("No medications recorded yet.")


# ── Feature 4 — Safeguarding Flags ───────────────────────────────────────────

_FLAG_TYPES = [
    "Child protection concern",
    "Adult safeguarding concern",
    "Domestic violence indicator",
    "Mental capacity concern (MCA assessment needed)",
    "Elderly -- no care package in place",
    "No fixed abode",
    "Discharge Against Medical Advice (DAMA)",
]

_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _render_safeguarding(pathway: dict, pkey: str) -> None:
    """Safeguarding flags management section."""
    nhs = pathway["nhs_number"]
    patient = get_patient(nhs) or {}
    flags   = get_safeguarding_flags(nhs)
    active  = [f for f in flags if not f.get("resolved")]

    st.markdown(
        '<div class="section-heading">Safeguarding Flags</div>',
        unsafe_allow_html=True,
    )

    if active:
        for f in active:
            st.error(
                f"FLAG: {f['flag_type']} | By: {f['flagged_by']} "
                f"| {_fmt_dt(f.get('flagged_at'), 10)} | {f['details'][:80]}"
            )

    st.markdown("**Add New Safeguarding Flag**")
    with st.form(key=f"sg_form_{pkey}"):
        flag_type  = st.selectbox("Flag Type", _FLAG_TYPES, key=f"sg_type_{pkey}")
        flagged_by = st.selectbox(
            "Flagged By", [d["name"] for d in _DOCTORS] + ["Nursing Staff", "Social Worker"],
            key=f"sg_by_{pkey}",
        )
        details      = st.text_area("Details of concern", height=80, key=f"sg_det_{pkey}")
        action_taken = st.text_area("Action already taken", height=60, key=f"sg_act_{pkey}")
        referred_to  = st.text_input("Referred to", key=f"sg_ref_{pkey}",
                                      placeholder="e.g. Surrey County Council Social Services")
        ref_number   = st.text_input("Reference Number", key=f"sg_refno_{pkey}")
        urgency      = st.radio("Urgency", ["Urgent", "Non-urgent"],
                                 horizontal=True, key=f"sg_urg_{pkey}")

        # Extra fields if DAMA selected
        is_dama = flag_type == "Discharge Against Medical Advice (DAMA)"
        if is_dama:
            st.markdown("**DAMA — Additional Information**")
            patient_statement = st.text_area(
                "Patient Statement", height=80, key=f"sg_dama_stmt_{pkey}",
                placeholder="Patient's reason for wishing to leave...",
            )
            clinical_risks = st.text_area(
                "Clinical Risks of Self-Discharge", height=80,
                key=f"sg_dama_risks_{pkey}",
            )
            witness = st.text_input("Witness Name", key=f"sg_dama_wit_{pkey}")
        else:
            patient_statement = ""
            clinical_risks    = ""
            witness           = ""

        submitted = st.form_submit_button("Raise Flag", type="primary")

    if submitted:
        if not details.strip():
            st.warning("Details of concern are required.")
        else:
            from datetime import date as _date
            save_safeguarding_flag(
                nhs, flag_type, str(_date.today()), flagged_by,
                details, action_taken, referred_to, ref_number,
            )
            st.success(f"Safeguarding flag raised: {flag_type}")
            st.rerun()

    # Document generation for DAMA / social services referral
    st.markdown("---")
    st.markdown("**Generate Documents**")
    doc_col1, doc_col2 = st.columns(2)

    with doc_col1:
        if st.button("Generate DAMA Form (.docx)", key=f"dama_btn_{pkey}"):
            dama_data = {
                "ward":               pathway["stages"].get(5, {}).get("data", {}).get("ward_name", ""),
                "hospital":           pathway["stages"].get(5, {}).get("data", {}).get("hospital", "East Surrey Hospital"),
                "clinician":          pathway["stages"].get(3, {}).get("data", {}).get("assigned_doctor", ""),
                "patient_statement":  "",
                "clinical_risks":     "Clinical risks documented in medical notes.",
                "witness":            "",
                "discharge_datetime": datetime.now().strftime("%d/%m/%Y %H:%M"),
            }
            st.session_state[f"dama_doc_{pkey}"] = (
                letter_generator.generate_dama_form(nhs, dama_data)
            )
        if f"dama_doc_{pkey}" in st.session_state:
            st.download_button(
                "Download DAMA Form (.docx)",
                data=st.session_state[f"dama_doc_{pkey}"],
                file_name=f"dama_form_{nhs.replace(' ', '_')}.docx",
                mime=_DOCX_MIME,
                key=f"dama_dl_{pkey}",
            )

    with doc_col2:
        sg_flags_needing_referral = [
            f for f in active
            if "protection" in f["flag_type"].lower() or "safeguarding" in f["flag_type"].lower()
        ]
        if sg_flags_needing_referral:
            if st.button("Generate Social Services Referral (.docx)",
                          key=f"sg_ref_btn_{pkey}"):
                flag_for_doc = sg_flags_needing_referral[0]
                flag_for_doc["urgency"] = "Urgent"
                st.session_state[f"sg_ref_doc_{pkey}"] = (
                    letter_generator.generate_safeguarding_referral(
                        nhs, flag_for_doc, patient
                    )
                )
            if f"sg_ref_doc_{pkey}" in st.session_state:
                dl_col1, dl_col2 = st.columns(2)
                with dl_col1:
                    st.download_button(
                        "Download Referral (.docx)",
                        data=st.session_state[f"sg_ref_doc_{pkey}"],
                        file_name=f"safeguarding_referral_{nhs.replace(' ', '_')}.docx",
                        mime=_DOCX_MIME,
                        key=f"sg_ref_dl_{pkey}",
                    )
                with dl_col2:
                    if st.button("Email Referral", key=f"sg_ref_email_{pkey}"):
                        ok, msg = letter_generator.send_letter_email(
                            to_email=st.session_state.get("smtp_to", ""),
                            subject=f"[SAFEGUARDING] Surrey Social Services Referral -- NHS {nhs}",
                            body="Please find attached a safeguarding referral letter.",
                            docx_bytes=st.session_state[f"sg_ref_doc_{pkey}"],
                            filename=f"safeguarding_referral_{nhs.replace(' ', '_')}.docx",
                        )
                        st.success(msg) if ok else st.warning(msg)
        else:
            st.info("Raise a Child Protection or Adult Safeguarding flag to unlock referral letter.")

    if flags:
        st.markdown(f"**All flags ({len(flags)} total):**")
        for f in flags:
            status = "RESOLVED" if f.get("resolved") else "ACTIVE"
            with st.expander(f"{status} — {f['flag_type']} — {_fmt_dt(f.get('flagged_at'), 10)}"):
                st.markdown(f"**By:** {f['flagged_by']}")
                st.markdown(f"**Details:** {f['details']}")
                st.markdown(f"**Action:** {f['action_taken'] or 'None recorded'}")
                st.markdown(f"**Referred to:** {f['referred_to'] or 'N/A'}")
                st.markdown(f"**Ref #:** {f['reference_number'] or 'N/A'}")


# ── Feature 5 — Discharge Planning Checklist ─────────────────────────────────

_CHECKLIST_ITEMS = [
    ("summary_completed",   "Discharge summary completed",                         True),
    ("gp_letter_sent",      "GP letter generated and sent",                        True),
    ("tto_prescribed",      "TTO medications prescribed",                          True),
    ("followup_booked",     "Follow-up appointment booked",                        True),
    ("patient_understands", "Patient understands diagnosis and treatment",          True),
    ("meds_explained",      "Patient understands medications",                     True),
    ("transport_arranged",  "Transport arranged",                                  False),
    ("care_package",        "Care package in place (if needed)",                   False),
    ("social_services",     "Social services notified (if applicable)",            False),
    ("nok_informed",        "Next of kin informed",                                False),
    ("accompanied",         "Patient accompanied on discharge",                    False),
    ("equipment_provided",  "Medical equipment provided (if needed)",              False),
    ("community_nursing",   "Community nursing referral made (if needed)",         False),
]


def _render_discharge_checklist_section(pathway: dict, pkey: str) -> bool:
    """
    Render the pre-discharge checklist and return True if all required items
    are checked (safe to allow discharge save).
    """
    nhs       = pathway["nhs_number"]
    checklist = get_discharge_checklist(nhs)

    st.markdown("### Pre-Discharge Checklist")
    st.caption(
        "Items marked * are required before discharge can be recorded. "
        "Tick each item and sign off with your name."
    )

    with st.form(key=f"checklist_form_{pkey}"):
        updated = {}
        for item_key, item_label, required in _CHECKLIST_ITEMS:
            existing = checklist.get(item_key, {})
            c1, c2, c3 = st.columns([3, 1, 2])
            with c1:
                label = f"{'* ' if required else ''}{item_label}"
                checked = st.checkbox(
                    label, value=existing.get("checked", False),
                    key=f"cl_{item_key}_{pkey}",
                )
            with c2:
                signed_by = st.text_input(
                    "Signed by", value=existing.get("signed_by", ""),
                    key=f"cls_{item_key}_{pkey}", label_visibility="collapsed",
                    placeholder="Initials",
                )
            with c3:
                ts_display = _fmt_dt(existing.get("timestamp"), 16).replace("T", " ")
                st.caption(ts_display or "Not signed")
            updated[item_key] = {
                "checked":   checked,
                "signed_by": signed_by,
                "timestamp": (
                    existing.get("timestamp") or
                    (datetime.now().isoformat() if checked else "")
                ),
            }

        save_cl = st.form_submit_button("Save Checklist", type="primary")

    if save_cl:
        # Preserve existing timestamps when item was already signed
        for k, v in updated.items():
            if not v["checked"]:
                v["timestamp"] = ""
            elif not checklist.get(k, {}).get("checked"):
                v["timestamp"] = datetime.now().isoformat()
            else:
                v["timestamp"] = checklist.get(k, {}).get("timestamp", v["timestamp"])
        update_discharge_checklist(nhs, updated)
        st.success("Checklist saved.")
        st.rerun()

    required_done = all(
        checklist.get(k, {}).get("checked", False)
        for k, _, req in _CHECKLIST_ITEMS if req
    )
    if required_done:
        st.success("All required items complete — discharge can be recorded.")
    else:
        missing = [
            label for k, label, req in _CHECKLIST_ITEMS
            if req and not checklist.get(k, {}).get("checked", False)
        ]
        st.warning(
            "Complete required checklist items before saving discharge:\n"
            + "\n".join(f"- {m}" for m in missing)
        )

    # Download checklist as Word doc
    if st.button("Download Checklist (.docx)", key=f"cl_dl_btn_{pkey}"):
        cl_doc = letter_generator.generate_discharge_checklist_doc(
            nhs, get_discharge_checklist(nhs), pathway
        )
        st.session_state[f"cl_docx_{pkey}"] = cl_doc
    if f"cl_docx_{pkey}" in st.session_state:
        st.download_button(
            "Save Checklist (.docx)",
            data=st.session_state[f"cl_docx_{pkey}"],
            file_name=f"discharge_checklist_{nhs.replace(' ','_')}.docx",
            mime=_DOCX_MIME,
            key=f"cl_dl_{pkey}",
        )

    st.markdown("---")
    return required_done


# ── Feature 6 — Pathway Timeline View ────────────────────────────────────────

_TIMELINE_COLOURS = {
    "triage":      "#005EB8",
    "pathway":     "#6B7280",
    "assignment":  "#059669",
    "referral":    "#7C3AED",
    "ward_log":    "#0891B2",
    "observation": "#D97706",
    "medication":  "#BE185D",
    "safeguarding": "#DC2626",
}


def _render_timeline(nhs: str, pkey: str) -> None:
    """Vertical colour-coded patient journey timeline."""
    with st.expander("Patient Journey Timeline", expanded=False):
        events = get_patient_timeline(nhs)
        if not events:
            st.info("No timeline events yet.")
            return

        items_html = []
        for ev in reversed(events):  # newest first
            colour = _TIMELINE_COLOURS.get(ev["category"], "#6B7280")
            ts     = _fmt_dt(ev.get("ts"), 16).replace("T", " ")
            items_html.append(
                f'<div style="display:flex;align-items:flex-start;margin-bottom:12px;">'
                f'  <div style="width:12px;height:12px;border-radius:50%;'
                f'background:{colour};flex-shrink:0;margin-top:4px;margin-right:12px;"></div>'
                f'  <div style="flex:1;border-left:2px solid {colour};'
                f'padding-left:10px;padding-bottom:8px;">'
                f'    <div style="font-size:0.78rem;color:#6B7280;">{ts}</div>'
                f'    <div style="font-weight:700;color:{colour};font-size:0.9rem;">'
                f'{ev["stage"]}</div>'
                f'    <div style="font-size:0.88rem;color:#374151;">{ev["action"]}</div>'
                f'    <div style="font-size:0.78rem;color:#9CA3AF;">{ev["clinician"]}</div>'
                f'  </div>'
                f'</div>'
            )

        legend_html = "".join(
            f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;'
            f'background:{col};margin-right:4px;"></span>'
            f'<span style="font-size:0.78rem;margin-right:12px;">{cat.replace("_"," ").title()}</span>'
            for cat, col in _TIMELINE_COLOURS.items()
        )

        st.markdown(
            f'<div style="padding:8px;background:#F0F4F5;border-radius:6px;'
            f'margin-bottom:12px;">{legend_html}</div>'
            f'<div style="max-height:500px;overflow-y:auto;padding:12px;'
            f'background:#ffffff;border:1px solid #AEB7BD;border-radius:6px;">'
            + "".join(items_html)
            + "</div>",
            unsafe_allow_html=True,
        )

        st.caption(f"Total events: {len(events)}")


# ── Letter section (rendered below stages) ────────────────────────────────────

def _doctor_email(pathway: dict) -> str:
    """Resolve the assigned doctor's email from pathway stage 3."""
    from tabs.triage_tab import _DOCTORS as _TAB_DOCTORS
    doc_name = pathway["stages"].get(3, {}).get("data", {}).get("assigned_doctor", "")
    return next(
        (d["email"] for d in _TAB_DOCTORS if doc_name.startswith(d["name"])),
        "",
    )


_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _render_letters_section(pathway: dict, pkey: str) -> None:
    st.markdown("---")
    st.subheader("Clinical Letters")
    st.caption(
        "NHS-branded Word documents (.docx) with Trust letterhead, "
        "NHS colours, and ICD-10/SNOMED codes."
    )

    s6_done  = pathway["stages"].get(6,  {}).get("status") == "complete"
    s10_done = pathway["stages"].get(10, {}).get("status") == "complete"
    nhs      = pathway["nhs_number"]
    nhs_slug = nhs.replace(" ", "_")

    lc1, lc2 = st.columns(2)

    # ── Diagnosis letter ─────────────────────────────────────────────────────
    with lc1:
        st.markdown("**Diagnosis Confirmation Letter (to GP)**")
        if s6_done:
            if st.button("Generate Diagnosis Letter (.docx)", key=f"gen_dx_{pkey}"):
                st.session_state[f"dx_docx_{pkey}"] = (
                    letter_generator.generate_diagnosis_letter(nhs, pathway)
                )
            if f"dx_docx_{pkey}" in st.session_state:
                st.success("NHS Word document ready.")
                dcol1, dcol2 = st.columns(2)
                with dcol1:
                    st.download_button(
                        "Download (.docx)",
                        data=st.session_state[f"dx_docx_{pkey}"],
                        file_name=f"diagnosis_letter_{nhs_slug}.docx",
                        mime=_DOCX_MIME,
                        key=f"dl_dx_{pkey}",
                    )
                with dcol2:
                    if st.button("Email Letter", key=f"email_dx_{pkey}"):
                        ok, msg = letter_generator.send_letter_email(
                            to_email=_doctor_email(pathway),
                            subject=f"[GP Triage] Diagnosis Confirmation — NHS {nhs}",
                            body=(
                                "Dear GP,\n\nPlease find attached the diagnosis "
                                "confirmation letter.\n\n— GP Triage System"
                            ),
                            docx_bytes=st.session_state[f"dx_docx_{pkey}"],
                            filename=f"diagnosis_letter_{nhs_slug}.docx",
                        )
                        st.success(msg) if ok else st.warning(msg)
        else:
            st.info("Complete Stage 6 (Diagnosis) to unlock.")

    # ── Discharge letter ─────────────────────────────────────────────────────
    with lc2:
        st.markdown("**Discharge Summary (to GP)**")
        if s10_done:
            if st.button("Generate Discharge Summary (.docx)", key=f"gen_dc_{pkey}"):
                st.session_state[f"dc_docx_{pkey}"] = (
                    letter_generator.generate_discharge_letter(nhs, pathway)
                )
            if f"dc_docx_{pkey}" in st.session_state:
                st.success("NHS Word document ready.")
                dcol1, dcol2 = st.columns(2)
                with dcol1:
                    st.download_button(
                        "Download (.docx)",
                        data=st.session_state[f"dc_docx_{pkey}"],
                        file_name=f"discharge_summary_{nhs_slug}.docx",
                        mime=_DOCX_MIME,
                        key=f"dl_dc_{pkey}",
                    )
                with dcol2:
                    if st.button("Email Summary", key=f"email_dc_{pkey}"):
                        ok, msg = letter_generator.send_letter_email(
                            to_email=_doctor_email(pathway),
                            subject=f"[GP Triage] Discharge Summary — NHS {nhs}",
                            body=(
                                "Dear GP,\n\nPlease find attached the discharge "
                                "summary for your records.\n\n— GP Triage System"
                            ),
                            docx_bytes=st.session_state[f"dc_docx_{pkey}"],
                            filename=f"discharge_summary_{nhs_slug}.docx",
                        )
                        st.success(msg) if ok else st.warning(msg)
        else:
            st.info("Complete Stage 10 (Discharge) to unlock.")


# ── Main render ────────────────────────────────────────────────────────────────

def render_pathway() -> None:
    """Render the Patient Pathway Tracker tab."""
    if "pathways" not in st.session_state:
        st.session_state.pathways = {}
    if "show_new_pathway_form" not in st.session_state:
        st.session_state.show_new_pathway_form = False

    pathways       = st.session_state.pathways
    triage_history = [e for e in st.session_state.get("triage_history", []) if "result" in e]

    st.subheader("Patient Pathway Tracker")
    st.caption(
        "End-to-end 10-stage clinical pathway from presentation to discharge. "
        "**Stages 1–4 auto-populate from Triage tab data.** "
        "Stages 5–10 are manually entered (demo simulation — "
        "in production these integrate with EPR/PAS)."
    )

    # ── Pathway selector / new pathway button ────────────────────────────────
    st.markdown("---")
    sel_col, btn_col = st.columns([4, 1])

    with sel_col:
        if pathways:
            selected_nhs = st.selectbox(
                "Select Active Pathway",
                list(pathways.keys()),
                format_func=lambda k: (
                    f"NHS {k}  —  Stage {pathways[k]['current_stage']}/10: "
                    f"{STAGE_LABELS.get(pathways[k]['current_stage'], 'Discharge')}"
                ),
                key="pathway_selector",
            )
        else:
            st.info("No active pathways. Click **+ New Pathway** to create one.")
            selected_nhs = None

    with btn_col:
        if st.button("+ New Pathway", key="new_pathway_btn", use_container_width=True):
            st.session_state.show_new_pathway_form = True

    # ── New pathway form ─────────────────────────────────────────────────────
    if st.session_state.show_new_pathway_form:
        with st.form(key="new_pathway_form"):
            st.subheader("Create New Patient Pathway")
            nhs_input = st.text_input(
                "NHS Number",
                placeholder="e.g. 485 777 3456",
                help="Enter the patient's 10-digit NHS number.",
            )
            case_options = ["None (manual entry)"] + [
                f"Case {i + 1} — {e['result']['triage_decision']} — "
                f"{e['timestamp'][:16].replace('T', ' ')}"
                for i, e in enumerate(triage_history)
            ]
            linked_case = st.selectbox(
                "Link to Triage Result (auto-fills Stages 1–4)",
                case_options,
            )
            form_submitted = st.form_submit_button("Create Pathway", type="primary")

        if form_submitted:
            nhs_clean = nhs_input.strip()
            if not nhs_clean:
                st.warning("Please enter an NHS number.")
            elif nhs_clean in pathways:
                st.warning(f"A pathway for NHS {nhs_clean} already exists.")
            else:
                case_idx = None
                if linked_case != "None (manual entry)":
                    try:
                        case_idx = int(linked_case.split(" ")[1]) - 1
                    except (ValueError, IndexError):
                        case_idx = None
                pathways[nhs_clean] = _make_new_pathway(nhs_clean, case_idx)

                # Persist patient and any auto-filled stages to DB
                save_patient(nhs_clean)
                for snum, sdata in pathways[nhs_clean]["stages"].items():
                    if sdata.get("status") == "complete":
                        save_pathway_stage(
                            nhs_clean, snum, STAGE_LABELS[snum],
                            "complete", sdata.get("data", {}),
                        )

                st.session_state.show_new_pathway_form = False
                st.success(f"Pathway created for NHS {nhs_clean}.")
                st.rerun()

    # ── Render selected pathway ──────────────────────────────────────────────
    if not selected_nhs or selected_nhs not in pathways:
        return

    pathway = pathways[selected_nhs]
    pkey    = selected_nhs.replace(" ", "_")
    stages  = pathway["stages"]
    cur     = pathway["current_stage"]

    # Safeguarding banner — shown at top if any active flags
    active_flags = [
        f for f in get_safeguarding_flags(selected_nhs)
        if not f.get("resolved")
    ]
    if active_flags:
        st.error(
            f"SAFEGUARDING ALERT — {len(active_flags)} active flag(s) for this patient:"
        )
        for f in active_flags:
            st.error(f"  * {f['flag_type']} | {f['flagged_by']} | {f['details'][:80]}")

    # Stepper
    _render_stepper(stages, cur)

    # Summary metrics
    completed_count = sum(1 for s in stages.values() if s.get("status") == "complete")
    all_done        = completed_count == 10
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Stages Complete", f"{completed_count}/10")
    mc2.metric("Active Stage", f"{cur} — {STAGE_LABELS.get(cur, 'Discharge')}")
    mc3.metric("Status", "Discharged" if all_done else "In Progress")
    mc4.metric("Created", _fmt_dt(pathway["created_at"], 10))

    if all_done:
        st.success("This patient has been fully discharged. All 10 stages are complete.")

    st.markdown("---")

    # ── All 10 stages as expanders ───────────────────────────────────────────
    for stage_num in range(1, 11):
        stage_data  = stages.get(stage_num, {"status": "pending", "timestamp": None, "data": {}})
        status      = stage_data.get("status", "pending")
        timestamp   = stage_data.get("timestamp")
        is_current  = (stage_num == cur)
        is_complete = (status == "complete")

        if is_complete:
            exp_label = f"✅ Stage {stage_num} — {STAGE_LABELS[stage_num]}"
        elif is_current:
            exp_label = f"🔵 Stage {stage_num} — {STAGE_LABELS[stage_num]}  (ACTIVE)"
        else:
            exp_label = f"⬜ Stage {stage_num} — {STAGE_LABELS[stage_num]}"

        with st.expander(exp_label, expanded=is_current):
            _stage_header(
                stage_num,
                "in_progress" if is_current else status,
                timestamp,
            )

            if is_complete and stage_num <= 4:
                st.success("Auto-filled from Triage tab data.")
                _show_readonly(stage_data)

            elif is_complete and stage_num > 4:
                _show_readonly(stage_data)
                if st.button(
                    f"Edit Stage {stage_num}",
                    key=f"edit_{stage_num}_{pkey}",
                ):
                    stages[stage_num]["status"] = "pending"
                    if pathway["current_stage"] > stage_num:
                        pathway["current_stage"] = stage_num
                    st.rerun()

            elif is_current:
                renderer = _STAGE_RENDERERS.get(stage_num)
                if renderer:
                    renderer(pathway, pkey)
                elif stage_num <= 4:
                    st.info(
                        f"Stage {stage_num} data was not found in session. "
                        "Complete the Triage tab (assign a doctor / generate referrals) "
                        "then create a new pathway linked to that result."
                    )

            else:
                st.caption("Not yet reached. Complete earlier stages to unlock.")

    # ── Ward Management (Path A features — visible once admitted) ────────────
    if cur >= 5 or stages.get(5, {}).get("status") == "complete":
        st.markdown("---")
        st.markdown(
            '<div class="section-heading">Ward Management</div>',
            unsafe_allow_html=True,
        )
        wm_tab1, wm_tab2, wm_tab3, wm_tab4 = st.tabs([
            "Daily Ward Log",
            "Nurse Observations (NEWS2)",
            "Medication Record (MAR)",
            "Safeguarding",
        ])
        with wm_tab1:
            _render_ward_log(pathway, pkey)
        with wm_tab2:
            _render_observations(pathway, pkey)
        with wm_tab3:
            _render_medications(pathway, pkey)
        with wm_tab4:
            _render_safeguarding(pathway, pkey)

    # ── Letters ──────────────────────────────────────────────────────────────
    _render_letters_section(pathway, pkey)

    # ── Patient Journey Timeline ──────────────────────────────────────────────
    st.markdown("---")
    _render_timeline(selected_nhs, pkey)

    # ── Full pathway export ──────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Export Full Pathway")
    pathway_export = {
        "nhs_number":    pathway["nhs_number"],
        "created_at":    pathway["created_at"],
        "current_stage": pathway["current_stage"],
        "stages": {str(k): v for k, v in pathway["stages"].items()},
    }
    csv_rows = ["Stage,Name,Status,Timestamp"]
    for n in range(1, 11):
        s = pathway["stages"].get(n, {})
        csv_rows.append(
            f"{n},{STAGE_LABELS[n]},{s.get('status','pending')},"
            f"{s.get('timestamp') or ''}"
        )

    ec1, ec2 = st.columns(2)
    with ec1:
        st.download_button(
            "Download Full Pathway (JSON)",
            data=json.dumps(pathway_export, indent=2),
            file_name=f"pathway_{pkey}_{datetime.now().strftime('%Y%m%d')}.json",
            mime="application/json",
            key=f"dl_pathway_json_{pkey}",
        )
    with ec2:
        st.download_button(
            "Download Stage Summary (CSV)",
            data="\n".join(csv_rows),
            file_name=f"pathway_stages_{pkey}_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            key=f"dl_pathway_csv_{pkey}",
        )
