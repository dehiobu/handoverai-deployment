"""
tabs/pathway_tab.py — NHS GP Clinical Pathway Tracker (restructured).

10-stage workflow reflecting actual NHS GP practice:
  1  Presentation       — auto-filled from Triage tab
  2  GP Triage          — AI triage result (auto-filled)
  3  Consultation       — One or more GP consultations; exam, plan, follow-up
  4  Investigations     — Bloods, imaging, other tests ordered
  5  Referral           — Specialist (eReferral) / Emergency / Imaging-only
  6  Admission          — Hospital admission (if applicable)
  7  Discharge Summary  — Summary received back from hospital
  8  Follow-up          — Post-hospital or post-result GP review
  9  Ongoing Care       — Repeat prescriptions, community referrals, monitoring
 10  Case Closure       — Retention date, NHS App notification, record sealed
"""
from __future__ import annotations

import json
from datetime import date, datetime

import streamlit as st

from src import letter_generator
from src.database import (
    # core
    save_patient, save_pathway_stage, get_patient,
    # consultations
    save_consultation, get_consultations,
    # investigations
    save_test_order, update_test_result, get_test_orders,
    # referrals
    save_referral_full, get_referrals,
    # admissions / discharge
    save_hospital_admission, get_hospital_admissions,
    save_discharge_summary, get_discharge_summaries,
    # case closure + NHS App
    save_case_closure, get_case_closure, calculate_retention_date,
    save_nhs_app_notification, get_nhs_app_notifications,
    # ward management
    save_ward_log, get_ward_logs,
    save_observation, get_observations,
    save_medication, get_medications,
    save_safeguarding_flag, get_safeguarding_flags,
    update_discharge_checklist, get_discharge_checklist,
    get_patient_timeline,
    save_shift_handover, get_shift_handovers,
)
from src.auth import get_user_name, get_user_email


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_dt(dt, chars: int = 16) -> str:
    """Safely format a datetime, date, or string to a fixed-length string."""
    if dt is None:
        return ""
    if isinstance(dt, (datetime, date)):
        s = dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        s = str(dt)
    return s[:chars]


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

STAGE_LABELS = {
    1:  "Presentation",
    2:  "GP Triage",
    3:  "Consultation",
    4:  "Investigations",
    5:  "Referral",
    6:  "Admission",
    7:  "Discharge Summary",
    8:  "Follow-up",
    9:  "Ongoing Care",
    10: "Case Closure",
}

# ---------------------------------------------------------------------------
# Lookup lists
# ---------------------------------------------------------------------------

_GPS = [
    "Dr D. Ehiobu",
    "Dr S. Morrison",
    "Dr A. Patel (GP)",
]

_SPECIALISTS = [
    "Dr D. Wake-Trent — Cardiologist, East Surrey Hospital",
    "Dr R. Chen — Respiratory Consultant, East Surrey Hospital",
    "Dr A. Patel — Paediatrician, East Surrey Hospital",
    "Dr L. Okafor — Ophthalmologist, London Eye Hospital",
    "Dr M. Singh — Orthopaedics, East Surrey Hospital",
    "Dr F. Adams — Gastroenterology, East Surrey Hospital",
]

_HOSPITALS = ["East Surrey Hospital", "Royal Surrey Hospital", "St George's Hospital",
               "King's College Hospital", "Epsom Hospital"]

_DEPARTMENTS = ["Cardiology", "Respiratory", "Orthopaedics", "Gastroenterology",
                 "Neurology", "Oncology", "Paediatrics", "Ophthalmology", "A&E",
                 "General Medicine", "General Surgery"]

_TEST_TYPES  = ["Blood test", "Imaging", "Microbiology", "ECG", "Spirometry",
                "Biopsy", "Urine test", "Stool test", "Other"]

_BLOOD_TESTS = ["FBC", "U&E", "LFT", "TFT", "HbA1c", "Lipid profile",
                "CRP/ESR", "INR/Coag", "Troponin", "D-Dimer",
                "PSA", "Blood cultures", "Ferritin/B12/Folate",
                "Thyroid function", "Bone profile", "CK"]

_IMAGING     = ["CXR", "AXR", "CT Head", "CT Chest", "CT Abdomen/Pelvis",
                "CT Angiogram", "MRI Brain", "MRI Spine", "USS Abdomen",
                "USS Pelvis", "Echocardiogram", "DEXA Scan", "PET Scan"]

_DISCHARGE_DESTINATIONS = ["Home", "Residential care", "Nursing home",
                            "Rehabilitation unit", "Transfer to another trust",
                            "Self-discharge"]

_REFERRAL_URGENCY = ["Routine (18-week pathway)", "Urgent (2-week wait)", "Emergency (<24h)"]

_CLOSURE_REASONS = ["Episode complete", "Patient deceased", "Patient transferred to another practice",
                    "Care transferred to secondary care", "Patient request", "Other"]

_COMMUNITY_REFS = ["District Nurse", "Physiotherapy", "Occupational Therapy",
                   "Mental Health Team", "Social Services", "Community Nursing",
                   "Palliative Care", "IAPT"]

_NOTIFICATION_TYPES = ["Test result ready", "Referral sent", "Appointment booked",
                        "Prescription ready", "Follow-up reminder",
                        "Discharge summary received", "Case closed"]

_SURGERIES = ["Holmhurst Medical Centre", "Woodlands Surgery", "Greystone House Surgery"]

_HANDOVER_USERS = ["Dr D. Ehiobu", "Dr S. Morrison", "Nurse Jones",
                   "Dr D. Wake-Trent", "Practice Manager"]


# ---------------------------------------------------------------------------
# Pathway factory
# ---------------------------------------------------------------------------

def _make_new_pathway(nhs_number: str,
                      triage_case_idx: int | None = None,
                      name: str = "",
                      age: str = "",
                      gender: str = "") -> dict:
    """Return a fresh in-memory pathway, auto-filling stages 1-2 from triage."""
    now    = datetime.now().isoformat()
    stages = {i: {"status": "pending", "timestamp": None, "data": {}} for i in range(1, 11)}
    current_stage = 1

    if triage_case_idx is not None:
        history = st.session_state.get("triage_history", [])
        if triage_case_idx < len(history):
            entry  = history[triage_case_idx]
            result = entry.get("result", {})

            stages[1] = {
                "status": "complete", "timestamp": entry.get("timestamp", now),
                "data": {
                    "patient_description": entry.get("input", ""),
                    "presentation_time":   entry.get("timestamp", now),
                },
            }
            stages[2] = {
                "status": "complete", "timestamp": entry.get("timestamp", now),
                "data": {
                    "ai_decision":     result.get("triage_decision", ""),
                    "urgency":         result.get("urgency_timeframe", ""),
                    "confidence":      result.get("confidence", ""),
                    "response_time_s": entry.get("response_time"),
                    "override":        entry.get("override"),
                },
            }
            current_stage = 3

    return {
        "nhs_number":      nhs_number,
        "created_at":      now,
        "name":            name,
        "age":             age,
        "gender":          gender,
        "triage_case_idx": triage_case_idx,
        "current_stage":   current_stage,
        "stages":          stages,
    }


# ---------------------------------------------------------------------------
# Visual stepper
# ---------------------------------------------------------------------------

def _render_stepper(stages: dict, current_stage: int) -> None:
    circles = []
    for i in range(1, 11):
        status = stages.get(i, {}).get("status", "pending")
        if status == "complete":
            bg, fg, icon, lc = "#009639", "#ffffff", "✓", "#009639"
        elif i == current_stage:
            bg, fg, icon, lc = "#005EB8", "#ffffff", str(i), "#005EB8"
        else:
            bg, fg, icon, lc = "#AEB7BD", "#ffffff", str(i), "#6B7280"
        circles.append(
            f'<div style="text-align:center;flex:0 0 auto;">'
            f'<div style="width:34px;height:34px;border-radius:50%;background:{bg};'
            f'color:{fg};display:flex;align-items:center;justify-content:center;'
            f'font-weight:700;font-size:0.88rem;margin:0 auto;">{icon}</div>'
            f'<div style="font-size:0.62rem;color:{lc};font-weight:600;'
            f'margin-top:4px;max-width:60px;line-height:1.2;">'
            f'{STAGE_LABELS[i]}</div></div>'
        )

    parts = []
    for idx, circle in enumerate(circles):
        parts.append(circle)
        if idx < len(circles) - 1:
            done       = stages.get(idx + 1, {}).get("status") == "complete"
            conn_color = "#009639" if done else "#D1D5DB"
            parts.append(
                f'<div style="flex:1;height:2px;background:{conn_color};'
                f'min-width:6px;align-self:center;margin-bottom:20px;"></div>'
            )

    html = (
        '<div style="display:flex;align-items:flex-start;gap:2px;'
        'padding:16px;background:#F0F4F5;border-radius:8px;'
        'border:1px solid #AEB7BD;margin-bottom:16px;overflow-x:auto;">'
        + "".join(parts) + "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Stage header badge
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Read-only completed stage data display
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Stage 1 — Presentation (auto-filled / read-only)
# ---------------------------------------------------------------------------

def _render_stage_1(pathway: dict, pkey: str) -> None:
    stage = pathway["stages"][1]
    if stage["status"] == "complete":
        _show_readonly(stage)
        return

    with st.form(key=f"s1_{pkey}"):
        st.caption("Enter patient presentation details or auto-fill from Triage tab.")
        desc = st.text_area("Patient Presentation", height=120,
                             placeholder="Describe why the patient is attending...")
        ptime = st.text_input("Presentation Date/Time",
                               value=datetime.now().strftime("%Y-%m-%d %H:%M"))
        submitted = st.form_submit_button("Save Stage 1 — Presentation", type="primary")

    if submitted and desc:
        data = {"patient_description": desc, "presentation_time": ptime}
        pathway["stages"][1] = {
            "status": "complete", "timestamp": datetime.now().isoformat(), "data": data,
        }
        save_pathway_stage(pathway["nhs_number"], 1, STAGE_LABELS[1], "complete", data)
        if pathway["current_stage"] <= 1:
            pathway["current_stage"] = 2
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 2 — GP Triage (auto-filled / read-only)
# ---------------------------------------------------------------------------

def _render_stage_2(pathway: dict, pkey: str) -> None:
    stage = pathway["stages"][2]
    if stage["status"] == "complete":
        data = stage.get("data", {})
        decision = data.get("ai_decision", "")
        col = {"RED": "#DA291C", "AMBER": "#FFB81C", "GREEN": "#009639"}.get(decision, "#005EB8")
        if decision:
            st.markdown(
                f'<div style="background:{col};color:#fff;padding:10px 16px;'
                f'border-radius:6px;font-size:1.1rem;font-weight:700;margin-bottom:8px;">'
                f'AI Triage Decision: {decision}</div>',
                unsafe_allow_html=True,
            )
        _show_readonly(stage)
        return

    with st.form(key=f"s2_{pkey}"):
        st.caption("Record initial triage assessment.")
        c1, c2 = st.columns(2)
        with c1:
            decision = st.selectbox("Triage Decision", ["RED", "AMBER", "GREEN"])
            urgency  = st.text_input("Urgency Timeframe",
                                      placeholder="e.g. Immediate/Within 2h/Routine")
        with c2:
            confidence = st.selectbox("AI Confidence", ["High", "Medium", "Low"])
        submitted = st.form_submit_button("Save Stage 2 — GP Triage", type="primary")

    if submitted:
        data = {"ai_decision": decision, "urgency": urgency, "confidence": confidence}
        pathway["stages"][2] = {
            "status": "complete", "timestamp": datetime.now().isoformat(), "data": data,
        }
        save_pathway_stage(pathway["nhs_number"], 2, STAGE_LABELS[2], "complete", data)
        if pathway["current_stage"] <= 2:
            pathway["current_stage"] = 3
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 3 — GP Consultation (multiple consultations supported)
# ---------------------------------------------------------------------------

def _render_stage_3(pathway: dict, pkey: str) -> None:
    nhs    = pathway["nhs_number"]
    consults = get_consultations(nhs)

    if consults:
        st.markdown("**Existing Consultations**")
        for c in consults:
            with st.expander(
                f"NHS {nhs}  —  {_fmt_dt(c.get('consultation_date'), 10)}  —  "
                f"{c.get('gp_name', '')}  |  {c.get('presenting_complaint', '')[:60]}"
            ):
                st.markdown(f"**NHS Number:** {nhs}")
                for k in ["gp_name", "presenting_complaint", "examination_findings",
                          "assessment", "plan", "plan_detail",
                          "follow_up_date", "follow_up_gp", "follow_up_surgery"]:
                    v = c.get(k, "")
                    if v:
                        st.markdown(f"**{k.replace('_', ' ').title()}:** {v}")

    st.markdown("---")
    st.markdown("**Add Consultation**")
    with st.form(key=f"s3_{pkey}_{len(consults)}"):
        c1, c2 = st.columns(2)
        with c1:
            cons_date    = st.date_input("Consultation Date", value=date.today())
            gp_name      = st.selectbox("GP", _GPS)
            gp_email     = st.text_input("GP Email", value=f"{gp_name.lower().replace(' ','').replace('.','_')}@holmhurst.nhs.uk")
        with c2:
            follow_up_dt = st.date_input("Follow-up Date (if applicable)",
                                          value=date.today(), key=f"fud_{pkey}")
            follow_up_gp  = st.selectbox("Follow-up GP", ["Same GP"] + _GPS)
            follow_up_surg = st.selectbox("Follow-up Surgery", _SURGERIES)
        complaint = st.text_area("Presenting Complaint", height=80,
                                  placeholder="Chief complaint in patient's words...")
        exam      = st.text_area("Examination Findings", height=80,
                                  placeholder="Vital signs, auscultation, etc...")
        assess    = st.text_area("Assessment / Working Diagnosis", height=80,
                                  placeholder="Clinical impression, differentials...")
        plan      = st.selectbox("Immediate Plan", [
            "Safety-net and monitor", "Investigations ordered",
            "Referral to specialist", "Emergency admission", "Prescribe",
            "Physiotherapy / community referral", "Other",
        ])
        plan_detail = st.text_area("Plan Detail", height=80,
                                    placeholder="Specific actions, prescriptions, safety-net advice...")
        submitted = st.form_submit_button("Save Consultation", type="primary")

    if submitted and complaint:
        cid = save_consultation(
            nhs_number=nhs,
            consultation_date=str(cons_date),
            gp_name=gp_name,
            gp_email=gp_email,
            presenting_complaint=complaint,
            examination_findings=exam,
            assessment=assess,
            plan=plan,
            plan_detail=plan_detail,
            follow_up_date=str(follow_up_dt),
            follow_up_gp=follow_up_gp,
            follow_up_surgery=follow_up_surg,
            created_by=get_user_name(),
        )
        stage_data = {
            "consultation_count": len(consults) + 1,
            "last_consultation":  str(cons_date),
            "last_gp":            gp_name,
            "last_plan":          plan,
            "last_assessment":    assess[:120],
        }
        pathway["stages"][3] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data,
        }
        save_pathway_stage(nhs, 3, STAGE_LABELS[3], "complete", stage_data)
        if pathway["current_stage"] <= 3:
            pathway["current_stage"] = 4
        st.success(f"Consultation saved (ID {cid}).")
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 4 — Investigations (bloods + imaging)
# ---------------------------------------------------------------------------

def _render_stage_4(pathway: dict, pkey: str) -> None:
    nhs    = pathway["nhs_number"]
    orders = get_test_orders(nhs)

    if orders:
        st.markdown("**Test Orders**")
        for o in orders:
            flag_color = {"abnormal": "#FFB81C", "critical": "#DA291C"}.get(
                o.get("result_flag", "normal"), "#009639"
            )
            status_badge = (
                f'<span style="background:{flag_color};color:#fff;padding:2px 8px;'
                f'border-radius:4px;font-size:0.75rem;">'
                f'{o.get("status","pending").upper()}</span>'
            )
            with st.expander(
                f"NHS {nhs}  —  {o.get('test_name','')} ({o.get('test_type','')})  —  "
                f"Ordered {_fmt_dt(o.get('ordered_date'), 10)}"
            ):
                st.markdown(status_badge, unsafe_allow_html=True)
                st.markdown(f"**NHS Number:** {nhs}")
                for k in ["test_name", "test_type", "ordered_date", "ordered_by",
                          "status", "result_date", "result_summary",
                          "result_flag", "gp_review_notes", "action_after_result"]:
                    v = o.get(k, "")
                    if v:
                        st.markdown(f"**{k.replace('_', ' ').title()}:** {v}")

                # Enter result inline
                if o.get("status") == "pending":
                    with st.form(key=f"result_{o['id']}"):
                        rdate = st.date_input("Result Date", value=date.today(),
                                               key=f"rd_{o['id']}")
                        rsumm = st.text_area("Result Summary", height=60)
                        rflag = st.selectbox("Result Flag",
                                              ["normal", "abnormal", "critical"],
                                              key=f"rf_{o['id']}")
                        rnotes = st.text_area("GP Review Notes", height=60)
                        raction = st.text_input("Action After Result")
                        if st.form_submit_button("Save Result", type="primary"):
                            update_test_result(
                                o["id"], str(rdate), rsumm, rflag, rnotes, raction
                            )
                            st.rerun()

    st.markdown("---")
    st.markdown("**Order New Test**")
    with st.form(key=f"s4_{pkey}_{len(orders)}"):
        c1, c2 = st.columns(2)
        with c1:
            test_type  = st.selectbox("Test Category", _TEST_TYPES)
            order_date = st.date_input("Order Date", value=date.today())
            ordered_by = st.selectbox("Ordered By", _GPS)
        with c2:
            notify_app = st.checkbox("Notify patient via NHS App when result ready")

        # Dynamic test name based on category
        if test_type == "Blood test":
            test_name = st.multiselect("Blood Tests", _BLOOD_TESTS)
            test_name_str = ", ".join(test_name)
        elif test_type == "Imaging":
            test_name = st.selectbox("Imaging Type", _IMAGING)
            test_name_str = test_name
        else:
            test_name_str = st.text_input("Test Name",
                                           placeholder="Specify test name...")

        submitted = st.form_submit_button("Order Test", type="primary")

    if submitted and test_name_str:
        tid = save_test_order(
            nhs_number=nhs,
            test_name=test_name_str,
            test_type=test_type,
            ordered_date=str(order_date),
            ordered_by=ordered_by,
            notify_nhs_app=notify_app,
        )
        if notify_app:
            save_nhs_app_notification(
                nhs_number=nhs,
                notification_type="Test result ready",
                notification_content=f"Your {test_name_str} result will be available soon. Your GP will review it and contact you if action is needed.",
                sent_by=get_user_name(),
            )
        stage_data = {
            "test_count": len(orders) + 1,
            "latest_test": test_name_str,
            "test_type":   test_type,
            "ordered":     str(order_date),
        }
        pathway["stages"][4] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data,
        }
        save_pathway_stage(nhs, 4, STAGE_LABELS[4], "complete", stage_data)
        if pathway["current_stage"] <= 4:
            pathway["current_stage"] = 5
        st.success(f"Test order saved (ID {tid}).")
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 5 — Referral (three types)
# ---------------------------------------------------------------------------

def _render_stage_5(pathway: dict, pkey: str) -> None:
    nhs      = pathway["nhs_number"]
    referrals = get_referrals(nhs)

    if referrals:
        st.markdown("**Existing Referrals**")
        for r in referrals:
            cat = r.get("referral_category", r.get("referral_type", ""))
            with st.expander(
                f"NHS {nhs}  —  {cat}  —  {r.get('referral_name', '')}  |  "
                f"{r.get('urgency', '')}  |  {r.get('ereferral_status', r.get('status', ''))}"
            ):
                st.markdown(f"**NHS Number:** {nhs}")
                for k in ["referral_category", "referral_name", "urgency",
                          "hospital_name", "department", "specialty",
                          "ereferral_reference", "ereferral_status",
                          "email_sent", "created_at"]:
                    v = r.get(k)
                    if v is not None and v != "":
                        label = k.replace("_", " ").title()
                        st.markdown(f"**{label}:** {v}")

    st.markdown("---")
    st.markdown("**Create Referral**")
    with st.form(key=f"s5_{pkey}_{len(referrals)}"):
        ref_cat = st.radio(
            "Referral Category",
            ["Specialist (eReferral)", "Emergency Admission", "Imaging / Diagnostic Only"],
            horizontal=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            urgency     = st.selectbox("Urgency", _REFERRAL_URGENCY)
            hosp        = st.selectbox("Hospital", _HOSPITALS)
            dept        = st.selectbox("Department", _DEPARTMENTS)
        with c2:
            specialist  = st.text_input(
                "Specialist / Consultant",
                placeholder="e.g. Dr D. Wake-Trent, Cardiology"
            )
            eref        = st.text_input("eReferral Reference", placeholder="e.g. RTT12345")
            email_sent  = st.checkbox("Referral letter emailed to hospital")

        ref_name = st.text_input(
            "Referral Name / Description",
            placeholder="e.g. Cardiology review — chest pain, abnormal ECG"
        )
        submitted = st.form_submit_button("Save Referral", type="primary")

    if submitted and ref_name:
        save_referral_full(
            nhs_number=nhs,
            referral_category=ref_cat,
            referral_type=ref_cat,
            referral_name=ref_name,
            urgency=urgency,
            hospital_name=hosp,
            department=dept,
            specialty=specialist,
            ereferral_reference=eref,
            ereferral_status="sent" if email_sent else "draft",
            email_sent=email_sent,
        )
        # NHS App notification for emergency
        if "Emergency" in ref_cat or "Emergency" in urgency:
            save_nhs_app_notification(
                nhs_number=nhs,
                notification_type="Referral sent",
                notification_content=(
                    f"An urgent referral has been sent to {hosp} — {dept}. "
                    "You will be contacted to arrange an appointment."
                ),
                sent_by=get_user_name(),
            )
        stage_data = {
            "referral_count": len(referrals) + 1,
            "latest_referral": ref_name[:80],
            "category":        ref_cat,
            "urgency":         urgency,
            "hospital":        hosp,
        }
        pathway["stages"][5] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data,
        }
        save_pathway_stage(nhs, 5, STAGE_LABELS[5], "complete", stage_data)
        if pathway["current_stage"] <= 5:
            pathway["current_stage"] = 6
        st.success("Referral saved.")
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 6 — Hospital Admission (optional)
# ---------------------------------------------------------------------------

def _render_stage_6(pathway: dict, pkey: str) -> None:
    nhs        = pathway["nhs_number"]
    admissions = get_hospital_admissions(nhs)

    if admissions:
        for a in admissions:
            with st.expander(
                f"NHS {nhs}  —  Admitted {_fmt_dt(a.get('admission_date'), 10)}  —  "
                f"{a.get('hospital_name', '')}  |  Ward: {a.get('ward', '')}"
            ):
                st.markdown(f"**NHS Number:** {nhs}")
                for k in ["admission_date", "hospital_name", "ward", "consultant",
                          "diagnosis", "treatment", "complications", "expected_discharge"]:
                    v = a.get(k, "")
                    if v:
                        st.markdown(f"**{k.replace('_', ' ').title()}:** {v}")

    st.markdown("---")
    st.info(
        "Complete this stage if the patient was admitted to hospital following referral. "
        "Skip if referral was outpatient or imaging only."
    )
    with st.form(key=f"s6_{pkey}"):
        c1, c2 = st.columns(2)
        with c1:
            admit_date = st.date_input("Admission Date", value=date.today())
            hosp       = st.selectbox("Hospital", _HOSPITALS)
            ward       = st.text_input("Ward", placeholder="e.g. Victoria Ward")
        with c2:
            consultant = st.text_input("Admitting Consultant")
            exp_dc     = st.date_input("Expected Discharge Date", value=date.today())
        diagnosis   = st.text_input("Admission Diagnosis")
        treatment   = st.text_area("Initial Treatment Plan", height=80)
        skip        = st.checkbox("Skip — patient not admitted (outpatient referral only)")
        submitted   = st.form_submit_button("Save Stage 6", type="primary")

    if submitted:
        if skip:
            stage_data = {"admission": "Not applicable — outpatient referral"}
        else:
            aid = save_hospital_admission(
                nhs_number=nhs,
                admission_date=str(admit_date),
                hospital_name=hosp,
                ward=ward,
                consultant=consultant,
                diagnosis=diagnosis,
                treatment=treatment,
                expected_discharge=str(exp_dc),
            )
            stage_data = {
                "admission_date": str(admit_date),
                "hospital":       hosp,
                "ward":           ward,
                "consultant":     consultant,
                "diagnosis":      diagnosis,
                "expected_discharge": str(exp_dc),
            }
        pathway["stages"][6] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data,
        }
        save_pathway_stage(nhs, 6, STAGE_LABELS[6], "complete", stage_data)
        if pathway["current_stage"] <= 6:
            pathway["current_stage"] = 7
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 7 — Discharge Summary (received from hospital)
# ---------------------------------------------------------------------------

def _render_stage_7(pathway: dict, pkey: str) -> None:
    nhs       = pathway["nhs_number"]
    summaries = get_discharge_summaries(nhs)

    if summaries:
        for s in summaries:
            with st.expander(
                f"NHS {nhs}  —  Discharge {_fmt_dt(s.get('discharge_date'), 10)}  —  "
                f"{s.get('diagnosis', '')[:60]}"
            ):
                st.markdown(f"**NHS Number:** {nhs}")
                for k in ["discharge_date", "discharge_destination", "diagnosis",
                          "treatment_given", "discharge_medications",
                          "follow_up_instructions", "gp_actions"]:
                    v = s.get(k, "")
                    if v:
                        st.markdown(f"**{k.replace('_', ' ').title()}:** {v}")

    st.markdown("---")
    st.info(
        "Record the discharge summary received from hospital. "
        "Skip if patient was not admitted (outpatient pathway)."
    )
    with st.form(key=f"s7_{pkey}"):
        c1, c2 = st.columns(2)
        with c1:
            dc_date   = st.date_input("Discharge Date", value=date.today())
            dc_dest   = st.selectbox("Discharge Destination", _DISCHARGE_DESTINATIONS)
        with c2:
            summary_received = st.checkbox("Summary received from hospital", value=True)
        diagnosis  = st.text_input("Discharge Diagnosis")
        treatment  = st.text_area("Treatment Given", height=80)
        meds       = st.text_area("Discharge Medications", height=60,
                                   placeholder="e.g. Bisoprolol 2.5mg OD, Aspirin 75mg OD...")
        fu_instr   = st.text_area("Follow-up Instructions from Hospital", height=60)
        gp_act     = st.text_area("GP Actions Required", height=60,
                                   placeholder="e.g. Review INR in 1 week, renal function at 6 weeks...")
        skip       = st.checkbox("Skip — no hospital admission on this pathway")
        submitted  = st.form_submit_button("Save Stage 7", type="primary")

    if submitted:
        if skip:
            stage_data = {"discharge_summary": "Not applicable — no hospital admission"}
        else:
            sid = save_discharge_summary(
                nhs_number=nhs,
                discharge_date=str(dc_date),
                discharge_destination=dc_dest,
                diagnosis=diagnosis,
                treatment_given=treatment,
                discharge_medications=meds,
                follow_up_instructions=fu_instr,
                gp_actions=gp_act,
            )
            save_nhs_app_notification(
                nhs_number=nhs,
                notification_type="Discharge summary received",
                notification_content=(
                    f"Your GP has received the discharge summary from hospital. "
                    f"You were discharged on {dc_date} to {dc_dest}. "
                    "Your GP will arrange follow-up as needed."
                ),
                sent_by=get_user_name(),
            )
            stage_data = {
                "discharge_date":      str(dc_date),
                "destination":         dc_dest,
                "diagnosis":           diagnosis,
                "gp_actions_required": gp_act[:120],
            }
        pathway["stages"][7] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data,
        }
        save_pathway_stage(nhs, 7, STAGE_LABELS[7], "complete", stage_data)
        if pathway["current_stage"] <= 7:
            pathway["current_stage"] = 8
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 8 — Follow-up Consultation (post-hospital or post-test results)
# ---------------------------------------------------------------------------

def _render_stage_8(pathway: dict, pkey: str) -> None:
    nhs = pathway["nhs_number"]

    # Show all previous consultations for context
    previous = get_consultations(nhs)
    if previous:
        with st.expander(f"Previous consultations — NHS {nhs} ({len(previous)})", expanded=False):
            for c in previous:
                st.markdown(
                    f"- **NHS {nhs}**  |  **{_fmt_dt(c.get('consultation_date'), 10)}** — "
                    f"{c.get('gp_name','')} — {c.get('presenting_complaint','')[:80]}"
                )

    # Pending test results
    pending = [o for o in get_test_orders(nhs) if o.get("status") == "pending"]
    if pending:
        st.warning(f"{len(pending)} pending test result(s) not yet reviewed.")

    st.markdown("**Record Follow-up Consultation**")
    with st.form(key=f"s8_{pkey}"):
        c1, c2 = st.columns(2)
        with c1:
            cons_date  = st.date_input("Follow-up Date", value=date.today())
            gp_name    = st.selectbox("GP", _GPS)
        with c2:
            fu_type    = st.selectbox("Follow-up Type", [
                "Post-hospital review", "Test result review",
                "Condition review", "Medication review", "Other",
            ])
        exam_findings = st.text_area("Examination / Review Findings", height=80)
        assess        = st.text_area("Assessment", height=80)
        plan          = st.text_area("Follow-up Plan", height=80)
        submitted     = st.form_submit_button("Save Follow-up Consultation", type="primary")

    if submitted and assess:
        cid = save_consultation(
            nhs_number=nhs,
            consultation_date=str(cons_date),
            gp_name=gp_name,
            presenting_complaint=f"[Follow-up] {fu_type}",
            examination_findings=exam_findings,
            assessment=assess,
            plan="Ongoing management",
            plan_detail=plan,
            created_by=get_user_name(),
        )
        stage_data = {
            "follow_up_date":  str(cons_date),
            "gp":              gp_name,
            "follow_up_type":  fu_type,
            "assessment":      assess[:120],
        }
        pathway["stages"][8] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data,
        }
        save_pathway_stage(nhs, 8, STAGE_LABELS[8], "complete", stage_data)
        if pathway["current_stage"] <= 8:
            pathway["current_stage"] = 9
        st.success(f"Follow-up consultation saved (ID {cid}).")
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 9 — Ongoing Care
# ---------------------------------------------------------------------------

def _render_stage_9(pathway: dict, pkey: str) -> None:
    nhs = pathway["nhs_number"]

    with st.form(key=f"s9_{pkey}"):
        st.markdown("**Ongoing Management Plan**")
        c1, c2 = st.columns(2)
        with c1:
            review_interval = st.selectbox("Review Interval", [
                "1 week", "2 weeks", "4 weeks (monthly)", "3 months",
                "6 months", "Annual review", "As needed (PRN)",
            ])
            repeat_meds = st.text_area(
                "Repeat Prescriptions Issued", height=80,
                placeholder="e.g. Ramipril 5mg OD, Atorvastatin 20mg ON..."
            )
        with c2:
            community_refs = st.multiselect("Community Referrals", _COMMUNITY_REFS)
            monitoring     = st.text_area(
                "Monitoring Required", height=80,
                placeholder="e.g. Annual HbA1c, BP check at 3 months, renal function..."
            )
        coded_conditions = st.text_area(
            "Coded Long-term Conditions (Read codes / SNOMED)", height=60,
            placeholder="e.g. Type 2 diabetes (E11), Hypertension (I10)..."
        )
        care_plan_note = st.text_area("Care Plan / Patient Advice", height=80)
        submitted = st.form_submit_button("Save Stage 9 — Ongoing Care", type="primary")

    if submitted:
        stage_data = {
            "review_interval":    review_interval,
            "repeat_medications": repeat_meds,
            "community_referrals": community_refs,
            "monitoring":         monitoring,
            "coded_conditions":   coded_conditions,
            "care_plan":          care_plan_note[:200],
        }
        pathway["stages"][9] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data,
        }
        save_pathway_stage(nhs, 9, STAGE_LABELS[9], "complete", stage_data)
        if pathway["current_stage"] <= 9:
            pathway["current_stage"] = 10
        st.rerun()


# ---------------------------------------------------------------------------
# Stage 10 — Case Closure
# ---------------------------------------------------------------------------

def _render_stage_10(pathway: dict, pkey: str) -> None:
    nhs         = pathway["nhs_number"]
    existing_cl = get_case_closure(nhs)

    if existing_cl:
        st.success("Case is closed.")
        st.markdown(f"**Closed:** {_fmt_dt(existing_cl.get('closed_date'), 10)}")
        st.markdown(f"**Closed by:** {existing_cl.get('closed_by', '')}")
        st.markdown(f"**Reason:** {existing_cl.get('closure_reason', '')}")
        st.markdown(f"**Retention Date:** {existing_cl.get('retention_date', '')}")
        if existing_cl.get("warning_flag"):
            st.warning("Retention warning: record due for review/deletion within 6 months.")
        st.markdown("---")
        _show_nhs_app_notifications(nhs)
        return

    # Get patient DOB for retention calculation
    patient    = get_patient(nhs)
    dob_str    = None
    if patient:
        # DOB not stored directly — compute from age field if possible
        age_str = patient.get("age", "")
        try:
            age = int(age_str)
            from datetime import timedelta
            dob_str = (date.today() - timedelta(days=age * 365)).isoformat()
        except (ValueError, TypeError):
            pass

    today          = date.today().isoformat()
    retention_date = calculate_retention_date(dob_str, today)

    st.info(
        f"Closing this case will seal the record and set a retention date. "
        f"Calculated retention date: **{retention_date}** "
        f"(NHS record retention policy)."
    )

    with st.form(key=f"s10_{pkey}"):
        c1, c2 = st.columns(2)
        with c1:
            closure_reason = st.selectbox("Reason for Closure", _CLOSURE_REASONS)
            notify_patient = st.checkbox("Send NHS App closure notification to patient")
        with c2:
            override_retention = st.checkbox("Override calculated retention date")
            if override_retention:
                custom_ret = st.date_input("Custom Retention Date",
                                            value=date.fromisoformat(retention_date))
            else:
                custom_ret = None
        case_summary = st.text_area(
            "Case Summary (for record)", height=120,
            placeholder="Brief summary of episode, key diagnoses, interventions..."
        )
        confirm_close = st.checkbox("I confirm this case is ready to be closed")
        submitted     = st.form_submit_button("Close Case", type="primary")

    if submitted and confirm_close:
        final_retention = str(custom_ret) if custom_ret else retention_date
        save_case_closure(
            nhs_number=nhs,
            closed_by=get_user_name(),
            closure_reason=closure_reason,
            retention_date=final_retention,
            case_summary=case_summary,
            dob_str=dob_str,
        )
        if notify_patient:
            save_nhs_app_notification(
                nhs_number=nhs,
                notification_type="Case closed",
                notification_content=(
                    "Your GP episode has been closed. "
                    "Your health record is being retained as required by NHS policy. "
                    "Please contact your surgery if you have any concerns."
                ),
                sent_by=get_user_name(),
            )
        stage_data = {
            "closed_by":       get_user_name(),
            "closure_reason":  closure_reason,
            "retention_date":  final_retention,
            "case_summary":    case_summary[:200],
        }
        pathway["stages"][10] = {
            "status": "complete", "timestamp": datetime.now().isoformat(),
            "data": stage_data,
        }
        save_pathway_stage(nhs, 10, STAGE_LABELS[10], "complete", stage_data)
        pathway["current_stage"] = 10
        st.success("Case closed and record sealed.")
        st.rerun()

    elif submitted and not confirm_close:
        st.warning("Please tick the confirmation checkbox before closing the case.")


def _show_nhs_app_notifications(nhs: str) -> None:
    notifs = get_nhs_app_notifications(nhs)
    if not notifs:
        return
    st.markdown("**NHS App Notifications Sent**")
    for n in notifs:
        ts = _fmt_dt(n.get("sent_at"), 16).replace("T", " ")
        st.markdown(
            f'<div style="background:#E8F4FD;border-left:4px solid #005EB8;'
            f'padding:8px 12px;border-radius:4px;margin-bottom:6px;">'
            f'<strong>{n.get("notification_type","")}</strong> — {ts}<br>'
            f'<span style="font-size:0.85rem;">{n.get("notification_content","")}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Stage dispatcher
# ---------------------------------------------------------------------------

_STAGE_RENDERERS = {
    1: _render_stage_1,
    2: _render_stage_2,
    3: _render_stage_3,
    4: _render_stage_4,
    5: _render_stage_5,
    6: _render_stage_6,
    7: _render_stage_7,
    8: _render_stage_8,
    9: _render_stage_9,
    10: _render_stage_10,
}


# ---------------------------------------------------------------------------
# Ward Management (Path A — inpatient features)
# ---------------------------------------------------------------------------

def _render_ward_management(nhs: str, pathway: dict) -> None:
    """Expandable inpatient / ward section — SOAP logs, NEWS2, MAR, safeguarding, checklist."""
    # Only show if patient has been admitted (stage 6 complete)
    admitted = pathway["stages"].get(6, {}).get("status") == "complete"
    skip_flag = pathway["stages"].get(6, {}).get("data", {}).get("admission") == "Not applicable — outpatient referral"
    if not admitted or skip_flag:
        return

    st.markdown("---")
    st.markdown(
        '<div style="background:#005EB8;color:#fff;padding:8px 16px;'
        'border-radius:6px;font-weight:700;margin-bottom:8px;">'
        'Ward Management (Inpatient)</div>',
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Daily Ward Log", "Observations (NEWS2)", "Medications (MAR)",
        "Safeguarding", "Discharge Checklist",
    ])

    # ── Daily Ward Log ────────────────────────────────────────────────────
    with tab1:
        logs = get_ward_logs(nhs)
        if logs:
            for log in logs[:5]:
                with st.expander(
                    f"NHS {nhs}  —  {_fmt_dt(log.get('log_date'), 10)} {log.get('shift','')} — "
                    f"{log.get('clinician','')} ({log.get('role','')})"
                ):
                    st.markdown(f"**NHS Number:** {nhs}")
                    for k in ["subjective", "objective", "assessment", "plan"]:
                        v = log.get(k, "")
                        if v:
                            st.markdown(f"**{k.title()}:** {v}")

        with st.form(f"ward_log_{nhs}_{len(logs)}"):
            c1, c2 = st.columns(2)
            with c1:
                log_date  = st.date_input("Date", value=date.today(), key=f"wld_{nhs}")
                shift     = st.selectbox("Shift", ["Morning", "Afternoon", "Evening", "Night"])
            with c2:
                clinician = st.text_input("Clinician Name")
                role_w    = st.selectbox("Role", ["GP", "Consultant", "Nurse", "Registrar", "HCA"])
            subj  = st.text_area("Subjective (Patient's account)", height=70)
            obj   = st.text_area("Objective (Examination findings / vitals)", height=70)
            assess= st.text_area("Assessment", height=70)
            plan  = st.text_area("Plan", height=70)
            if st.form_submit_button("Save Ward Log", type="primary"):
                save_ward_log(nhs, str(log_date), shift, clinician, role_w,
                              subj, obj, assess, plan)
                st.rerun()

    # ── Observations (NEWS2) ──────────────────────────────────────────────
    with tab2:
        # _calc_news2_score is defined at module level below — resolved at call time
        obs_list = get_observations(nhs)
        if obs_list:
            import pandas as pd
            obs_df = pd.DataFrame([{
                "NHS Number": nhs,
                "Date/Shift": f"{_fmt_dt(o.get('obs_date'), 10)} {o.get('shift','')}",
                "Nurse": o.get("nurse_name", ""),
                "Temp": o.get("temperature", ""),
                "BP": f"{o.get('bp_systolic','')}/{o.get('bp_diastolic','')}",
                "HR": o.get("heart_rate", ""),
                "RR": o.get("respiratory_rate", ""),
                "SpO2": o.get("o2_sats", ""),
                "AVPU": o.get("avpu", ""),
                "NEWS2": o.get("news2_score", ""),
            } for o in obs_list])
            st.dataframe(obs_df, use_container_width=True)

        with st.form(f"obs_{nhs}_{len(obs_list)}"):
            c1, c2 = st.columns(2)
            with c1:
                obs_date = st.date_input("Date", value=date.today(), key=f"od_{nhs}")
                shift_o  = st.selectbox("Shift", ["Morning", "Afternoon", "Evening", "Night"],
                                         key=f"so_{nhs}")
                nurse_n  = st.text_input("Nurse Name")
                temp     = st.number_input("Temp (°C)", 34.0, 42.0, 37.0, 0.1)
                bps      = st.number_input("BP Systolic",  50, 250, 120)
                bpd      = st.number_input("BP Diastolic", 30, 150, 80)
            with c2:
                hr   = st.number_input("Heart Rate", 20, 250, 75)
                rr   = st.number_input("Respiratory Rate", 4, 60, 16)
                o2   = st.number_input("SpO2 (%)", 50, 100, 97)
                avpu = st.selectbox("AVPU", ["Alert", "Voice", "Pain", "Unresponsive"])
                pain = st.slider("Pain Score", 0, 10, 0)
                fi   = st.number_input("Fluid In (ml)", 0, 5000, 0, 50)
                fo   = st.number_input("Fluid Out (ml)", 0, 5000, 0, 50)
            wc   = st.selectbox("Wound Check", ["Intact", "Clean", "Oozing", "Infected", "N/A"])
            pa   = st.selectbox("Pressure Areas", ["Normal", "Redness", "Breakdown", "N/A"])
            news2 = _calc_news2_score(temp, bps, hr, rr, o2, avpu)
            st.metric("NEWS2 Score", news2,
                      delta="HIGH ALERT" if news2 >= 7 else ("MEDIUM" if news2 >= 5 else "LOW"),
                      delta_color="inverse" if news2 >= 7 else "normal")
            if st.form_submit_button("Save Observations", type="primary"):
                save_observation(nhs, str(obs_date), shift_o, nurse_n, temp,
                                 bps, bpd, hr, rr, o2, avpu, pain, fi, fo,
                                 wc, pa, news2)
                st.rerun()

    # ── Medications (MAR) ─────────────────────────────────────────────────
    with tab3:
        meds = get_medications(nhs)
        if meds:
            import pandas as pd
            med_df = pd.DataFrame([{
                "NHS Number": nhs,
                "Date": _fmt_dt(m.get("med_date"), 10),
                "Drug": m.get("drug_name", ""),
                "Dose": m.get("dose", ""),
                "Route": m.get("route", ""),
                "Freq": m.get("frequency", ""),
                "Prescribed By": m.get("prescribed_by", ""),
                "Admin By": m.get("administered_by", ""),
                "Status": m.get("status", ""),
            } for m in meds])
            st.dataframe(med_df, use_container_width=True)

        with st.form(f"med_{nhs}_{len(meds)}"):
            c1, c2 = st.columns(2)
            with c1:
                med_date = st.date_input("Date", value=date.today(), key=f"mdd_{nhs}")
                drug     = st.text_input("Drug Name")
                dose     = st.text_input("Dose", placeholder="e.g. 10mg")
                route    = st.selectbox("Route", ["Oral", "IV", "IM", "SC", "Topical",
                                                   "Inhaled", "PR", "SL", "Other"])
            with c2:
                frequency  = st.selectbox("Frequency", ["OD", "BD", "TDS", "QDS",
                                                          "PRN", "Stat", "Other"])
                pres_by    = st.text_input("Prescribed By")
                admin_by   = st.text_input("Administered By")
                med_status = st.selectbox("Status", ["Given", "Withheld", "Refused",
                                                      "Not available", "Self-administered"])
            notes = st.text_input("Notes")
            if st.form_submit_button("Add Medication", type="primary"):
                save_medication(nhs, str(med_date), drug, dose, route, frequency,
                                pres_by, admin_by, med_status, notes)
                st.rerun()

    # ── Safeguarding ─────────────────────────────────────────────────────
    with tab4:
        flags = get_safeguarding_flags(nhs)
        if flags:
            for f in flags:
                color = "#DA291C" if not f.get("resolved") else "#009639"
                st.markdown(
                    f'<div style="border-left:4px solid {color};padding:8px;margin-bottom:8px;">'
                    f'<span style="font-size:0.75rem;color:#666;">NHS {nhs}</span><br>'
                    f'<strong>{f.get("flag_type","")}</strong> — '
                    f'{_fmt_dt(f.get("flagged_at"), 10)} — {f.get("flagged_by","")}<br>'
                    f'{f.get("details","")}</div>',
                    unsafe_allow_html=True,
                )

        with st.form(f"safe_{nhs}"):
            flag_type = st.selectbox("Flag Type", [
                "Child Protection (Section 47)", "Adult at Risk", "Domestic Violence",
                "Mental Capacity Act Concern", "DOLS", "DAMA", "FGM", "Other",
            ])
            flagged_by  = st.text_input("Flagged By (clinician name)")
            flagged_at  = st.date_input("Date Identified", value=date.today())
            details     = st.text_area("Details of Concern", height=80)
            action      = st.text_area("Action Taken", height=60)
            referred_to = st.text_input("Referred To (agency/team)")
            ref_no      = st.text_input("Reference Number")
            if st.form_submit_button("Raise Safeguarding Flag", type="primary"):
                save_safeguarding_flag(nhs, flag_type, str(flagged_at), flagged_by,
                                       details, action, referred_to, ref_no)
                st.rerun()

    # ── Discharge Checklist ───────────────────────────────────────────────
    with tab5:
        _CHECKLIST_ITEMS = [
            "Discharge summary completed",
            "GP letter sent",
            "Medications reconciled and dispensed",
            "TTO (To Take Out) medications provided",
            "Follow-up appointment booked",
            "Patient transport arranged (if needed)",
            "Carer / family informed",
            "Social services notified (if applicable)",
            "Community nursing referral made (if applicable)",
            "Physio / OT home assessment complete (if applicable)",
            "Patient aware of red flag symptoms to watch",
            "Discharge destination confirmed and safe",
            "Consultant sign-off obtained",
        ]
        cl_data = get_discharge_checklist(nhs)
        updated = dict(cl_data)
        all_done = True
        for item in _CHECKLIST_ITEMS:
            checked = st.checkbox(item, value=cl_data.get(item, False),
                                   key=f"dc_{nhs}_{item}")
            updated[item] = checked
            if not checked:
                all_done = False

        if st.button("Save Checklist", type="primary", key=f"dcbtn_{nhs}"):
            update_discharge_checklist(nhs, updated, get_user_name())
            st.rerun()

        if all_done:
            st.success("All discharge criteria met — patient ready for discharge.")
        else:
            pending_count = sum(1 for v in updated.values() if not v)
            st.warning(f"{pending_count} item(s) outstanding before discharge.")


# ---------------------------------------------------------------------------
# Patient Journey Timeline
# ---------------------------------------------------------------------------

def _render_timeline(nhs: str) -> None:
    events = get_patient_timeline(nhs)
    if not events:
        st.info("No timeline events yet.")
        return

    _CATEGORY_COLORS = {
        "triage":       "#DA291C",
        "pathway":      "#005EB8",
        "assignment":   "#6B7280",
        "referral":     "#FFB81C",
        "ward_log":     "#9333EA",
        "observation":  "#0891B2",
        "medication":   "#059669",
        "safeguarding": "#DC2626",
    }

    for ev in events:
        color = _CATEGORY_COLORS.get(ev.get("category", ""), "#005EB8")
        ts    = _fmt_dt(ev.get("ts"), 16).replace("T", " ")
        st.markdown(
            f'<div style="display:flex;gap:12px;margin-bottom:10px;">'
            f'<div style="width:4px;background:{color};border-radius:2px;'
            f'flex-shrink:0;"></div>'
            f'<div style="flex:1;">'
            f'<div style="font-size:0.75rem;color:#6B7280;">{ts}</div>'
            f'<div style="font-weight:600;color:{color};">'
            f'{ev.get("stage","")}</div>'
            f'<div style="font-size:0.88rem;">{ev.get("action","")}</div>'
            f'<div style="font-size:0.75rem;color:#6B7280;">'
            f'{ev.get("clinician","")}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Shift Handover (per-patient)
# ---------------------------------------------------------------------------

def _render_shift_handover(nhs: str) -> None:
    st.markdown("**Shift Handover**")
    handovers = get_shift_handovers(nhs)
    if handovers:
        latest = handovers[0]
        st.markdown(
            f"Latest handover: **{_fmt_dt(latest.get('handover_time'), 16)}** — "
            f"{latest.get('handed_from','')} → {latest.get('handed_to','')}"
        )
        if latest.get("handover_notes"):
            st.info(latest["handover_notes"])

    with st.form(f"handover_{nhs}"):
        c1, c2 = st.columns(2)
        with c1:
            from_user = st.selectbox("Handing Over From", _HANDOVER_USERS,
                                      key=f"hof_{nhs}")
        with c2:
            to_user   = st.selectbox("Handing Over To", _HANDOVER_USERS,
                                      key=f"hot_{nhs}")
        notes = st.text_area("Handover Notes", height=80)
        if st.form_submit_button("Record Handover", type="primary"):
            save_shift_handover(nhs, from_user, to_user, notes)
            st.rerun()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render_pathway_tracker() -> None:
    """Main entry point called from app.py."""
    st.subheader("NHS GP Patient Pathway Tracker")

    # ── New patient form ────────────────────────────────────────────────────
    with st.expander("Add / Load Patient", expanded=not st.session_state.get("pathways")):
        with st.form("new_patient_form"):
            c1, c2 = st.columns(2)
            with c1:
                nhs_input  = st.text_input("NHS Number",
                                            placeholder="e.g. 943-476-5919")
            with c2:
                name_input = st.text_input("Patient Name (optional)",
                                            placeholder="e.g. Jane Smith")
            c3, c4, c5 = st.columns(3)
            with c3:
                age_input = st.text_input("Age", placeholder="e.g. 68")
            with c4:
                gender_input = st.selectbox("Gender",
                                             ["Not specified", "Male", "Female", "Other"])
            with c5:
                pass  # spacer
            desc_input = st.text_area("Patient Description (brief)", height=60)

            # Auto-fill from triage history
            history = st.session_state.get("triage_history", [])
            triage_options = (
                [f"Case {i+1} — {h.get('result', {}).get('triage_decision','?')} — "
                 f"{h.get('input','')[:60]}" for i, h in enumerate(history)]
                if history else []
            )
            triage_idx = None
            if triage_options:
                selected = st.selectbox(
                    "Auto-fill stages 1-2 from triage session",
                    ["— None —"] + triage_options,
                )
                if selected != "— None —":
                    triage_idx = triage_options.index(selected)

            submitted = st.form_submit_button("Start Pathway", type="primary")

        if submitted and nhs_input:
            nhs = nhs_input.strip()
            if nhs in st.session_state.pathways:
                st.warning(f"NHS number {nhs} already loaded.")
            else:
                save_patient(nhs, age_input, gender_input, desc_input,
                             name=name_input.strip())
                pathway = _make_new_pathway(nhs, triage_idx,
                                            name=name_input.strip(),
                                            age=age_input, gender=gender_input)
                # Persist auto-filled stages
                for snum in [1, 2]:
                    s = pathway["stages"][snum]
                    if s["status"] == "complete":
                        save_pathway_stage(nhs, snum, STAGE_LABELS[snum],
                                           "complete", s["data"])
                st.session_state.pathways[nhs] = pathway
                st.success(f"Pathway started for NHS {nhs}.")
                st.rerun()

    # ── No pathways yet ──────────────────────────────────────────────────────
    if not st.session_state.get("pathways"):
        st.info("No patient pathways loaded. Use the form above to add a patient.")
        return

    # ── Patient selector ────────────────────────────────────────────────────
    nhs_list   = list(st.session_state.pathways.keys())

    def _patient_label(nhs: str) -> str:
        p      = st.session_state.pathways.get(nhs, {})
        name   = p.get("name", "")
        age    = p.get("age", "")
        gender = p.get("gender", "")
        demo   = f"{age}y {gender}".strip(" y") if (age or gender) else ""
        if name and demo:
            return f"{name} ({demo}) — NHS {nhs}"
        if name:
            return f"{name} — NHS {nhs}"
        if demo:
            return f"{demo} — NHS {nhs}"
        return f"NHS {nhs}"

    selected_nhs = st.selectbox("Select Patient", nhs_list,
                                  format_func=_patient_label)
    pathway    = st.session_state.pathways[selected_nhs]
    pkey       = selected_nhs.replace("-", "_").replace(" ", "_")

    # ── Persistent NHS number banner ─────────────────────────────────────────
    _p     = pathway
    _name  = _p.get("name", "")
    _age   = _p.get("age", "")
    _gender = _p.get("gender", "")
    _demo  = f"{_age}y {_gender}".strip() if (_age or _gender) else ""
    _label = f"{_name} — {_demo}" if (_name and _demo) else (_name or _demo or "")
    st.markdown(
        f'<div style="background:#005EB8;color:#fff;padding:6px 12px;'
        f'border-radius:4px;font-size:0.9rem;margin-bottom:8px;">'
        f'<strong>NHS Number: {selected_nhs}</strong>'
        f'{("  |  " + _label) if _label else ""}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Stepper ──────────────────────────────────────────────────────────────
    _render_stepper(pathway["stages"], pathway["current_stage"])

    # ── Case closure banner ─────────────────────────────────────────────────
    if pathway["stages"].get(10, {}).get("status") == "complete":
        st.success("This case is closed.")
        cl = get_case_closure(selected_nhs)
        if cl:
            st.markdown(
                f"**Retention Date:** {cl.get('retention_date','')}  |  "
                f"**Closed by:** {cl.get('closed_by','')}  |  "
                f"**Reason:** {cl.get('closure_reason','')}"
            )
        _show_nhs_app_notifications(selected_nhs)
        return

    # ── Stage tabs ───────────────────────────────────────────────────────────
    stage_tab_labels = [f"{i}. {STAGE_LABELS[i]}" for i in range(1, 11)]
    tabs = st.tabs(stage_tab_labels)

    for idx, tab in enumerate(tabs):
        stage_num = idx + 1
        with tab:
            stage = pathway["stages"].get(stage_num, {})
            _stage_header(stage_num, stage.get("status", "pending"),
                          stage.get("timestamp"))

            if stage.get("status") == "complete" and stage_num < pathway["current_stage"]:
                _show_readonly(stage)
                # Allow re-editing for consultation + investigations
                if stage_num in (3, 4, 5):
                    st.markdown("---")
                    with st.expander("Add another entry"):
                        _STAGE_RENDERERS[stage_num](pathway, pkey)
            else:
                _STAGE_RENDERERS[stage_num](pathway, pkey)

    # ── Ward management (inpatient) ─────────────────────────────────────────
    _render_ward_management(selected_nhs, pathway)

    # ── Extra panels ────────────────────────────────────────────────────────
    st.markdown("---")
    extra1, extra2 = st.columns(2)
    with extra1:
        with st.expander("Patient Journey Timeline", expanded=False):
            _render_timeline(selected_nhs)
    with extra2:
        with st.expander("Shift Handover", expanded=False):
            _render_shift_handover(selected_nhs)

    # ── NHS App Notifications ────────────────────────────────────────────────
    notifs = get_nhs_app_notifications(selected_nhs)
    if notifs:
        with st.expander(f"NHS App Notifications ({len(notifs)})", expanded=False):
            _show_nhs_app_notifications(selected_nhs)


# ---------------------------------------------------------------------------
# NEWS2 score helper (used by ward management)
# ---------------------------------------------------------------------------

def _calc_news2_score(temp: float, bps: int, hr: int, rr: int,
                      o2: int, avpu: str) -> int:
    """Calculate NEWS2 score from vital signs."""
    score = 0
    # Respiratory rate
    if rr <= 8 or rr >= 25:
        score += 3
    elif 21 <= rr <= 24:
        score += 2
    elif 9 <= rr <= 11:
        score += 1
    # SpO2
    if o2 <= 91:
        score += 3
    elif 92 <= o2 <= 93:
        score += 2
    elif 94 <= o2 <= 95:
        score += 1
    # Systolic BP
    if bps <= 90 or bps >= 220:
        score += 3
    elif 91 <= bps <= 100:
        score += 2
    elif 101 <= bps <= 110:
        score += 1
    # Heart rate
    if hr <= 40 or hr >= 131:
        score += 3
    elif 111 <= hr <= 130:
        score += 2
    elif 41 <= hr <= 50 or 91 <= hr <= 110:
        score += 1
    # Temperature
    if temp <= 35.0 or temp >= 39.1:
        score += 2
    elif 35.1 <= temp <= 36.0 or 38.1 <= temp <= 39.0:
        score += 1
    # AVPU (anything other than Alert = 3)
    if avpu != "Alert":
        score += 3
    return score


# Backwards-compatible alias for app.py import
render_pathway = render_pathway_tracker
