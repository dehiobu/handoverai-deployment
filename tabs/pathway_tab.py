"""
tabs/pathway_tab.py — 10-stage Patient Pathway Tracker.

Stages 1-4 auto-populate from Triage tab session data.
Stages 5-10 are manually entered (demo / simulation).
"""
import json
import os
import smtplib
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st
from dotenv import load_dotenv


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
    ts    = f" — {timestamp[:16].replace('T', ' ')}" if timestamp else ""
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
        pathway["stages"][5] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": {
                "admission_date":      str(admission_date),
                "ward_name":           ward_name,
                "bed_number":          bed_number,
                "admitting_consultant": admitting_cons,
                "admission_type":      admission_type,
                "hospital":            hospital,
                "admission_status":    adm_status,
            },
        }
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
        pathway["stages"][6] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": {
                "confirmed_diagnosis":  confirmed_dx,
                "icd10_code":           icd10,
                "snomed_code":          snomed,
                "diagnosing_consultant": dx_cons,
                "diagnosis_date":       str(dx_date),
                "diagnosis_status":     dx_status,
            },
        }
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
        pathway["stages"][7] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": {
                "treatment_type":   treatment_type,
                "procedure_name":   procedure_name,
                "theatre":          theatre,
                "anaesthetic_type": anaesthetic,
                "operating_surgeon": surgeon,
                "procedure_date":   str(proc_date),
                "duration_minutes": duration,
                "treatment_status": tx_status,
            },
        }
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
        pathway["stages"][8] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": {
                "outcome":           outcome,
                "complications":     complications or "None",
                "length_of_stay":    los,
                "follow_up_required": follow_up,
                "outcome_notes":     outcome_notes,
                "outcome_status":    oc_status,
            },
        }
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
        pathway["stages"][9] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": {
                "followup_date":         str(followup_date),
                "followup_location":     followup_loc,
                "followup_doctor":       followup_doctor,
                "medications":           medications,
                "aftercare_instructions": instructions,
                "community_referrals":   community_refs,
                "aftercare_status":      ac_status,
            },
        }
        if pathway["current_stage"] <= 9:
            pathway["current_stage"] = 10
        st.rerun()


# ── Stage 10 — Discharge ───────────────────────────────────────────────────────

def _render_stage_10(pathway: dict, pkey: str) -> None:
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
        submitted = st.form_submit_button("Save Stage 10 — Discharge", type="primary")

    if submitted:
        pathway["stages"][10] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": {
                "discharge_date":      str(discharge_date),
                "discharge_type":      discharge_type,
                "discharge_summary":   discharge_summary,
                "gp_notified":         gp_notified,
                "gp_letter_generated": gp_letter,
                "patient_accompanied": accompanied,
                "transport_arranged":  transport,
                "discharge_medications": discharge_meds,
                "discharge_status":    dc_status,
            },
        }
        # Stage 10 is the terminus — keep current_stage at 10
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


# ── Letter generators ──────────────────────────────────────────────────────────

def _nhs_header(nhs_number: str) -> list[str]:
    return [
        "Surrey and Sussex Healthcare NHS Trust",
        "East Surrey Hospital, Canada Avenue, Redhill, Surrey, RH1 5RH",
        f"Date: {datetime.now().strftime('%d %B %Y')}",
        f"NHS Number: {nhs_number}",
        "",
    ]


def _generate_diagnosis_letter(pathway: dict) -> str:
    nhs = pathway["nhs_number"]
    s1  = pathway["stages"].get(1,  {}).get("data", {})
    s2  = pathway["stages"].get(2,  {}).get("data", {})
    s3  = pathway["stages"].get(3,  {}).get("data", {})
    s6  = pathway["stages"].get(6,  {}).get("data", {})
    doc = s3.get("assigned_doctor", "Unknown Clinician")
    lines = _nhs_header(nhs) + [
        "DIAGNOSIS CONFIRMATION LETTER — TO GP",
        "=" * 60, "",
        "Dear GP,",
        "",
        "I am writing to inform you of the confirmed diagnosis for the "
        "above-named patient referred via the GP Triage system.",
        "",
        "PATIENT PRESENTATION:",
        s1.get("patient_description", "Not recorded"),
        "",
        f"AI TRIAGE DECISION : {s2.get('ai_decision', 'N/A')}",
        f"URGENCY            : {s2.get('urgency',     'N/A')}",
        "",
        "CONFIRMED DIAGNOSIS:",
        f"  Diagnosis        : {s6.get('confirmed_diagnosis', 'Pending')}",
        f"  ICD-10 Code      : {s6.get('icd10_code',  'N/A')}",
        f"  SNOMED CT Code   : {s6.get('snomed_code', 'N/A')}",
        f"  Diagnosis Date   : {s6.get('diagnosis_date', 'N/A')}",
        f"  Diagnosing Cons. : {s6.get('diagnosing_consultant', doc)}",
        "",
        "Please update your records accordingly.",
        "",
        "Yours sincerely,",
        "",
        doc,
        "Surrey and Sussex Healthcare NHS Trust",
        "(GMC number: [to be completed by clinician])",
        "",
        "DISCLAIMER: This letter was generated by the GP Triage AI system "
        "(demo simulation). In production, this integrates with EPR/PAS.",
    ]
    return "\n".join(lines)


def _generate_discharge_letter(pathway: dict) -> str:
    nhs  = pathway["nhs_number"]
    s1   = pathway["stages"].get(1,  {}).get("data", {})
    s2   = pathway["stages"].get(2,  {}).get("data", {})
    s3   = pathway["stages"].get(3,  {}).get("data", {})
    s5   = pathway["stages"].get(5,  {}).get("data", {})
    s6   = pathway["stages"].get(6,  {}).get("data", {})
    s7   = pathway["stages"].get(7,  {}).get("data", {})
    s8   = pathway["stages"].get(8,  {}).get("data", {})
    s9   = pathway["stages"].get(9,  {}).get("data", {})
    s10  = pathway["stages"].get(10, {}).get("data", {})
    doc  = s3.get("assigned_doctor", "Unknown Clinician")
    lines = _nhs_header(nhs) + [
        "DISCHARGE SUMMARY — TO GP",
        "=" * 60, "",
        "Dear GP,",
        "",
        "I am writing to inform you that the above patient has been "
        "discharged from our care.",
        "",
        "PATIENT PRESENTATION:",
        s1.get("patient_description", "Not recorded"),
        "",
        f"AI TRIAGE DECISION : {s2.get('ai_decision', 'N/A')}",
        f"URGENCY            : {s2.get('urgency',     'N/A')}",
        "",
        "ADMISSION DETAILS:",
        f"  Admission Date   : {s5.get('admission_date',      'N/A')}",
        f"  Ward             : {s5.get('ward_name',            'N/A')}",
        f"  Admission Type   : {s5.get('admission_type',       'N/A')}",
        f"  Admitting Cons.  : {s5.get('admitting_consultant', doc)}",
        "",
        "DIAGNOSIS:",
        f"  Confirmed Dx     : {s6.get('confirmed_diagnosis', 'N/A')}",
        f"  ICD-10 Code      : {s6.get('icd10_code',  'N/A')}",
        f"  SNOMED CT Code   : {s6.get('snomed_code', 'N/A')}",
        "",
        "TREATMENT:",
        f"  Treatment Type   : {s7.get('treatment_type',   'N/A')}",
        f"  Procedure        : {s7.get('procedure_name',   'N/A')}",
        f"  Surgeon          : {s7.get('operating_surgeon','N/A')}",
        "",
        "OUTCOME:",
        f"  Outcome          : {s8.get('outcome',           'N/A')}",
        f"  Complications    : {s8.get('complications',     'None')}",
        f"  Length of Stay   : {s8.get('length_of_stay',   'N/A')}",
        f"  Follow-up Req.   : {s8.get('follow_up_required','N/A')}",
        "",
        "AFTERCARE:",
        f"  Follow-up Appt   : {s9.get('followup_date',    'N/A')}",
        f"  Follow-up Doctor : {s9.get('followup_doctor',  'N/A')}",
        f"  Community Refs   : {', '.join(s9.get('community_referrals', [])) or 'None'}",
        f"  Instructions     : {s9.get('aftercare_instructions', 'N/A')}",
        "",
        "DISCHARGE DETAILS:",
        f"  Discharge Date   : {s10.get('discharge_date',  'N/A')}",
        f"  Discharge Type   : {s10.get('discharge_type',  'N/A')}",
        f"  Discharge Meds   : {s10.get('discharge_medications', 'None')}",
        "",
        "DISCHARGE SUMMARY:",
        s10.get("discharge_summary", ""),
        "",
        "Yours sincerely,",
        "",
        doc,
        "Surrey and Sussex Healthcare NHS Trust",
        "(GMC number: [to be completed by clinician])",
        "",
        "DISCLAIMER: This letter was generated by the GP Triage AI system "
        "(demo simulation). In production, this integrates with EPR/PAS.",
    ]
    return "\n".join(lines)


def _send_letter_email(pathway: dict, letter_text: str, subject: str) -> tuple[bool, str]:
    load_dotenv()
    user     = os.getenv("SMTP_EMAIL")
    password = os.getenv("SMTP_PASSWORD")
    if not user or not password:
        return False, "SMTP credentials not configured in .env."
    s3    = pathway["stages"].get(3, {}).get("data", {})
    doc_name = s3.get("assigned_doctor", "")
    to_email = next(
        (d["email"] for d in _DOCTORS if doc_name.startswith(d["name"])),
        user,
    )
    msg          = MIMEMultipart()
    msg["From"]  = user
    msg["To"]    = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(letter_text, "plain"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as srv:
            srv.login(user, password)
            srv.sendmail(user, to_email, msg.as_string())
        return True, f"Sent to {to_email}"
    except Exception as exc:
        return False, str(exc)


# ── Letter section (rendered below stages) ────────────────────────────────────

def _render_letters_section(pathway: dict, pkey: str) -> None:
    st.markdown("---")
    st.subheader("Clinical Letters")

    s6_done  = pathway["stages"].get(6,  {}).get("status") == "complete"
    s10_done = pathway["stages"].get(10, {}).get("status") == "complete"
    nhs      = pathway["nhs_number"]

    lc1, lc2 = st.columns(2)

    with lc1:
        st.markdown("**Diagnosis Confirmation Letter (to GP)**")
        if s6_done:
            if st.button("Generate Diagnosis Letter", key=f"gen_dx_{pkey}"):
                st.session_state[f"dx_letter_{pkey}"] = _generate_diagnosis_letter(pathway)
            if f"dx_letter_{pkey}" in st.session_state:
                st.text_area(
                    "Diagnosis Letter",
                    st.session_state[f"dx_letter_{pkey}"],
                    height=260,
                    key=f"dx_display_{pkey}",
                )
                dcol1, dcol2 = st.columns(2)
                with dcol1:
                    st.download_button(
                        "Download (.txt)",
                        data=st.session_state[f"dx_letter_{pkey}"],
                        file_name=f"diagnosis_letter_{nhs.replace(' ', '_')}.txt",
                        mime="text/plain",
                        key=f"dl_dx_{pkey}",
                    )
                with dcol2:
                    if st.button("Email Letter", key=f"email_dx_{pkey}"):
                        ok, msg = _send_letter_email(
                            pathway,
                            st.session_state[f"dx_letter_{pkey}"],
                            f"[GP Triage] Diagnosis Confirmation — NHS {nhs}",
                        )
                        st.success(msg) if ok else st.warning(msg)
        else:
            st.info("Complete Stage 6 (Diagnosis) to unlock.")

    with lc2:
        st.markdown("**Discharge Summary (to GP)**")
        if s10_done:
            if st.button("Generate Discharge Summary", key=f"gen_dc_{pkey}"):
                st.session_state[f"dc_letter_{pkey}"] = _generate_discharge_letter(pathway)
            if f"dc_letter_{pkey}" in st.session_state:
                st.text_area(
                    "Discharge Summary",
                    st.session_state[f"dc_letter_{pkey}"],
                    height=260,
                    key=f"dc_display_{pkey}",
                )
                dcol1, dcol2 = st.columns(2)
                with dcol1:
                    st.download_button(
                        "Download (.txt)",
                        data=st.session_state[f"dc_letter_{pkey}"],
                        file_name=f"discharge_summary_{nhs.replace(' ', '_')}.txt",
                        mime="text/plain",
                        key=f"dl_dc_{pkey}",
                    )
                with dcol2:
                    if st.button("Email Summary", key=f"email_dc_{pkey}"):
                        ok, msg = _send_letter_email(
                            pathway,
                            st.session_state[f"dc_letter_{pkey}"],
                            f"[GP Triage] Discharge Summary — NHS {nhs}",
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

    # Stepper
    _render_stepper(stages, cur)

    # Summary metrics
    completed_count = sum(1 for s in stages.values() if s.get("status") == "complete")
    all_done        = completed_count == 10
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Stages Complete", f"{completed_count}/10")
    mc2.metric("Active Stage", f"{cur} — {STAGE_LABELS.get(cur, 'Discharge')}")
    mc3.metric("Status", "Discharged" if all_done else "In Progress")
    mc4.metric("Created", pathway["created_at"][:10])

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

    # ── Letters ──────────────────────────────────────────────────────────────
    _render_letters_section(pathway, pkey)

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
