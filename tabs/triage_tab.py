"""
tabs/triage_tab.py — Triage tab UI and logic (Phases 1, 2, 3, 4).
"""
import json
import os
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st
from dotenv import load_dotenv

from ui.components import OVERRIDE_REASONS, render_explainability_panel, show_result
from src import letter_generator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WAITING_TIMES = {
    "RED":   "Immediate — see within 0–15 minutes",
    "AMBER": "Urgent — see within 1–2 hours",
    "GREEN": "Routine — see within 24–48 hours",
}

_SPECIALTIES = [
    "General Practice",
    "Cardiology",
    "Respiratory Medicine",
    "Paediatrics",
    "Ophthalmology",
    "Gastroenterology",
    "Neurology",
    "Orthopaedics",
    "Dermatology",
    "ENT",
    "Urology",
    "Psychiatry",
]

_DOCTORS = [
    {"name": "Dr. D. Ehiobu",     "role": "GP",                     "site": "Holmhurst Medical Centre", "email": "dennis.ehiobu@gmail.com"},
    {"name": "Dr. D. Wake-Trent", "role": "Cardiologist",            "site": "East Surrey Hospital",     "email": "dwake.trent@gmail.com"},
    {"name": "Dr. A. Patel",      "role": "Paediatrician",           "site": "East Surrey Hospital",     "email": "dehiobu@gmail.com"},
    {"name": "Dr. S. Morrison",   "role": "GP",                      "site": "Greystone House Surgery",  "email": "dehiobu@gmail.com"},
    {"name": "Dr. R. Chen",       "role": "Respiratory Consultant",  "site": "East Surrey Hospital",     "email": "dehiobu@gmail.com"},
    {"name": "Dr. L. Okafor",     "role": "Ophthalmologist",         "site": "London Eye Hospital",      "email": "dehiobu@gmail.com"},
]

_IMAGING = [
    "None",
    "Chest X-Ray",
    "Abdominal X-Ray",
    "CT Head (non-contrast)",
    "CT Chest / PE Protocol",
    "CT Abdomen & Pelvis",
    "MRI Brain",
    "MRI Spine",
    "Ultrasound Abdomen",
    "Ultrasound Pelvis",
    "Echocardiogram",
    "CTPA",
]

_BLOOD_TESTS = [
    "FBC (Full Blood Count)",
    "U&E (Urea & Electrolytes)",
    "LFTs (Liver Function Tests)",
    "CRP / ESR",
    "Troponin",
    "D-Dimer",
    "ABG (Arterial Blood Gas)",
    "Blood Glucose",
    "HbA1c",
    "Thyroid Function (TFTs)",
    "Coagulation Screen (INR/APTT)",
    "Blood Cultures",
    "Lactate",
    "BNP / NT-proBNP",
    "Iron Studies / Ferritin",
]


def _generate_referral_letter(result: dict, patient_input: str, doctor: dict,
                              specialty: str, imaging: list, bloods: list,
                              triage_lvl: str, urgency_txt: str, timestamp: str) -> str:
    """Build a plain-text referral letter from the current triage result."""
    date_str = timestamp[:10]
    lines = [
        f"Date: {date_str}",
        f"To: {doctor['name']} ({doctor['role']})",
        f"Site: {doctor['site']}",
        "",
        f"Re: GP Triage Referral — {specialty}",
        "=" * 60,
        "",
        f"Dear {doctor['name']},",
        "",
        "I am writing to refer the following patient for your assessment.",
        "",
        "PATIENT PRESENTATION:",
        patient_input,
        "",
        f"TRIAGE DECISION : {triage_lvl}",
        f"URGENCY         : {urgency_txt}",
        f"CONFIDENCE      : {result.get('confidence', 'N/A')}",
        "",
        "CLINICAL REASONING:",
        result.get("clinical_reasoning", ""),
        "",
        "RECOMMENDED ACTION:",
        result.get("recommended_action", ""),
        "",
        "RED FLAGS:",
        result.get("red_flags", "None identified"),
        "",
        "DIFFERENTIAL DIAGNOSIS:",
        result.get("differentials", "Not specified"),
        "",
        "NICE GUIDELINE:",
        result.get("nice_guideline", ""),
    ]
    if imaging:
        lines += ["", "IMAGING REQUESTED:", ", ".join(imaging)]
    if bloods:
        lines += ["", "BLOOD TESTS REQUESTED:", ", ".join(bloods)]
    lines += [
        "",
        "Yours sincerely,",
        "",
        "GP Triage System (AI-Assisted)",
        "This letter was generated automatically and requires clinician verification.",
    ]
    return "\n".join(lines)


def _send_assignment_email(doctor: dict, patient_input: str, triage_decision: str,
                            urgency: str, specialty: str) -> tuple[bool, str]:
    """
    Attempt to send an assignment alert via Gmail SMTP.

    Credentials are read from SMTP_EMAIL / SMTP_PASSWORD in .env.
    Falls back gracefully if not configured — returns (False, reason).
    """
    load_dotenv()
    user = os.getenv("SMTP_EMAIL")
    password = os.getenv("SMTP_PASSWORD")

    if not user or not password:
        st.warning("Email not configured - add SMTP_EMAIL and SMTP_PASSWORD to .env")
        return False, "SMTP credentials not configured in .env."

    subject = (
        f"[GP Triage] New {triage_decision} patient assigned — {specialty}"
    )
    body = (
        f"Dear {doctor['name']},\n\n"
        f"A patient has been assigned to you via the GP Triage system.\n\n"
        f"Triage Decision : {triage_decision}\n"
        f"Urgency         : {urgency}\n"
        f"Specialty       : {specialty}\n\n"
        f"Patient Presentation:\n{patient_input}\n\n"
        f"Please review at your earliest convenience.\n\n"
        f"— GP Triage System (automated alert)"
    )

    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = doctor["email"]
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(user, password)
            server.sendmail(user, doctor["email"], msg.as_string())
        return True, f"Email sent to {doctor['email']}"
    except Exception as exc:
        return False, str(exc)


def render_triage() -> None:
    """Render the Triage tab."""
    # Role guard — nurses and managers cannot run triage assessments
    from src.auth import can_access, get_user_role  # noqa: PLC0415
    if not can_access("triage"):
        role = get_user_role()
        st.info(
            f"The Triage tab is not available for your role ({role.title()}). "
            "Contact your administrator if you need access."
        )
        return

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
            # Triage card always visible above tabs
            show_result(entry["result"], entry["input"], case_idx)

            result      = entry["result"]
            triage_lvl  = result.get("triage_decision", "GREEN").upper()
            urgency_txt = result.get("urgency_timeframe", "")

            st.markdown("---")
            tab1, tab2, tab3, tab4, tab5 = st.tabs([
                "📋 Summary",
                "🧠 Explainability",
                "👨‍⚕️ Assign & Refer",
                "⚠️ Override",
                "📄 Letters & Export",
            ])

            # ── Tab 1: Summary ───────────────────────────────────────────────
            with tab1:
                wait_colour = {"RED": "red", "AMBER": "orange", "GREEN": "green"}.get(triage_lvl, "grey")
                wait_label  = _WAITING_TIMES.get(triage_lvl, "See clinician for guidance")
                st.markdown(
                    f'<div style="background:#f0f4f8;border-left:6px solid {wait_colour};'
                    f'padding:12px 16px;border-radius:4px;font-size:1rem;">'
                    f'<strong>{triage_lvl}</strong> &mdash; {wait_label}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("")
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

            # ── Tab 2: Explainability ────────────────────────────────────────
            with tab2:
                render_explainability_panel(result)
                st.markdown("---")
                with st.expander("Raw AI response"):
                    st.code(result["raw_response"], language="text")

            # ── Tab 3: Assign & Refer ────────────────────────────────────────
            with tab3:
                st.subheader("Specialty Assignment")
                specialty_key = f"specialty_{case_idx}"
                selected_specialty = st.selectbox(
                    "Assign to specialty:",
                    _SPECIALTIES,
                    key=specialty_key,
                )

                st.markdown("---")
                st.subheader("Doctor Assignment")
                # Filter by specialty keyword where possible; fall back to all doctors
                _kw = selected_specialty.split()[0].lower()[:5]
                filtered_doctors = [
                    d for d in _DOCTORS if _kw in d["role"].lower()
                ] or _DOCTORS
                doctor_labels = [
                    f"{d['name']} — {d['role']} ({d['site']})" for d in filtered_doctors
                ]
                doctor_key = f"doctor_{case_idx}_{selected_specialty}"
                selected_doctor_label = st.selectbox(
                    "Assign to clinician:",
                    doctor_labels,
                    key=doctor_key,
                )
                selected_doctor = filtered_doctors[doctor_labels.index(selected_doctor_label)]
                # Persist for Letters & Export tab
                st.session_state[f"selected_doctor_obj_{case_idx}"] = selected_doctor
                st.caption(f"Contact: {selected_doctor['email']}")

                assign_key = f"assign_btn_{case_idx}"
                if st.button("Assign & Send Email Alert", key=assign_key, type="primary"):
                    ok, msg = _send_assignment_email(
                        doctor=selected_doctor,
                        patient_input=entry["input"],
                        triage_decision=triage_lvl,
                        urgency=urgency_txt,
                        specialty=selected_specialty,
                    )
                    if ok:
                        st.success(f"Assigned to {selected_doctor['name']}. {msg}")
                    else:
                        st.warning(
                            f"Assignment recorded but email not sent: {msg}\n\n"
                            f"To enable email alerts, add SMTP credentials to your `.env` file:\n"
                            f"```\nSMTP_EMAIL=your@gmail.com\nSMTP_PASSWORD=your-app-password\n```"
                        )

                st.markdown("---")
                st.subheader("SMS Notification (Simulation)")
                if st.button("Send SMS Alert to Doctor", key=f"sms_{case_idx}"):
                    st.info(
                        f"[Simulated] SMS sent to {selected_doctor['name']}:\n"
                        f"'New {triage_lvl} patient assigned. Please review urgently.'"
                    )

                st.markdown("---")
                st.subheader("Imaging Referral — East Surrey Hospital")

                # Pre-suggested imaging defaults by triage level
                _imaging_defaults = {
                    "RED":   ["Chest X-Ray", "CT Chest / PE Protocol", "Echocardiogram"],
                    "AMBER": ["Chest X-Ray", "Ultrasound Abdomen"],
                    "GREEN": [],
                }
                _imaging_suggestions = _imaging_defaults.get(triage_lvl, [])

                st.markdown("""
<style>
.stMultiSelect > div {
    border: 2px solid #005EB8 !important;
    border-radius: 5px;
}
</style>
""", unsafe_allow_html=True)

                st.info("👆 Click the box below to select imaging studies")
                imaging_key = f"imaging_{case_idx}"
                # Only set defaults on first render (key not yet in session state)
                _imaging_init = (
                    _imaging_suggestions
                    if imaging_key not in st.session_state
                    else st.session_state[imaging_key]
                )
                selected_imaging = st.multiselect(
                    "Select imaging studies to request:",
                    [i for i in _IMAGING if i != "None"],
                    default=_imaging_init,
                    key=imaging_key,
                    placeholder="e.g. Chest X-Ray, ECG, CT Pulmonary Angiogram",
                )
                if selected_imaging:
                    st.info(
                        "Imaging requested: " + ", ".join(selected_imaging) +
                        "\nReferral destination: East Surrey Hospital Radiology"
                    )

                st.markdown("---")
                st.subheader("Blood Test Referrals")

                # Pre-suggested blood test defaults by triage level
                _bloods_defaults = {
                    "RED":   ["FBC (Full Blood Count)", "Troponin", "D-Dimer", "Lactate", "ABG (Arterial Blood Gas)"],
                    "AMBER": ["FBC (Full Blood Count)", "U&E (Urea & Electrolytes)", "CRP / ESR"],
                    "GREEN": [],
                }
                _bloods_suggestions = _bloods_defaults.get(triage_lvl, [])

                st.info("👆 Click the box below to select blood tests")
                bloods_key = f"bloods_{case_idx}"
                _bloods_init = (
                    _bloods_suggestions
                    if bloods_key not in st.session_state
                    else st.session_state[bloods_key]
                )
                selected_bloods = st.multiselect(
                    "Select blood tests to request:",
                    _BLOOD_TESTS,
                    default=_bloods_init,
                    key=bloods_key,
                    placeholder="e.g. FBC, U&E, Troponin, D-Dimer",
                )
                if selected_bloods:
                    st.info("Blood tests requested: " + ", ".join(selected_bloods))

                st.markdown("---")
                if st.button("Generate Referral Letter (.docx)", key=f"gen_letter_{case_idx}"):
                    # Plain text — for Print Summary / text preview
                    st.session_state[f"referral_letter_{case_idx}"] = _generate_referral_letter(
                        result=result,
                        patient_input=entry["input"],
                        doctor=selected_doctor,
                        specialty=selected_specialty,
                        imaging=st.session_state.get(imaging_key, []),
                        bloods=st.session_state.get(bloods_key, []),
                        triage_lvl=triage_lvl,
                        urgency_txt=urgency_txt,
                        timestamp=entry["timestamp"],
                    )
                    # NHS-branded Word document
                    st.session_state[f"referral_docx_{case_idx}"] = (
                        letter_generator.generate_referral_letter(
                            nhs_number=entry.get("nhs_number", "Not recorded"),
                            patient_description=entry["input"],
                            doctor=selected_doctor,
                            specialty=selected_specialty,
                            imaging=st.session_state.get(imaging_key, []),
                            blood_tests=st.session_state.get(bloods_key, []),
                            triage_result=result,
                            timestamp=entry["timestamp"],
                        )
                    )
                    st.success("Referral letter generated — download the Word doc in the Letters & Export tab.")

            # ── Tab 4: Override ──────────────────────────────────────────────
            with tab4:
                st.subheader("Clinician Override")
                existing = st.session_state.triage_history[case_idx].get("override")
                if existing:
                    detail_str = f" ({existing['reason_detail']})" if existing.get("reason_detail") else ""
                    st.success(
                        f"Override recorded: AI said **{triage_lvl}**, clinician changed to "
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
                        submitted = st.form_submit_button("Submit Override", type="primary")

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
                                "ai_original": triage_lvl,
                            }
                            st.session_state.triage_history[case_idx]["override"] = override_data
                            st.session_state.audit_log[case_idx]["clinician_override"] = override_data
                            st.success(
                                f"Override recorded: AI said {triage_lvl}, "
                                f"clinician changed to {override_decision}"
                            )
                            st.rerun()

            # ── Tab 5: Letters & Export ──────────────────────────────────────
            with tab5:
                docx_key   = f"referral_docx_{case_idx}"
                letter_key = f"referral_letter_{case_idx}"
                if docx_key in st.session_state or letter_key in st.session_state:
                    st.subheader("Generated Referral Letter")
                    st.success(
                        "NHS-branded Word document ready. "
                        "Download to open in Microsoft Word or compatible software."
                    )
                    _date_slug = entry["timestamp"][:10]
                    _doc_obj   = st.session_state.get(f"selected_doctor_obj_{case_idx}", _DOCTORS[0])
                    dl1, dl2, dl3 = st.columns(3)

                    # .docx download (primary)
                    with dl1:
                        if docx_key in st.session_state:
                            st.download_button(
                                "Download Letter (.docx)",
                                data=st.session_state[docx_key],
                                file_name=f"referral_letter_{_date_slug}.docx",
                                mime=(
                                    "application/vnd.openxmlformats-officedocument"
                                    ".wordprocessingml.document"
                                ),
                                key=f"dl_docx_{case_idx}",
                            )

                    # .txt fallback
                    with dl2:
                        if letter_key in st.session_state:
                            st.download_button(
                                "Download Letter (.txt)",
                                data=st.session_state[letter_key],
                                file_name=f"referral_letter_{_date_slug}.txt",
                                mime="text/plain",
                                key=f"dl_letter_{case_idx}",
                            )

                    # Email with attachment
                    with dl3:
                        if st.button("Email Letter (.docx)", key=f"email_letter_{case_idx}"):
                            _spec = st.session_state.get(f"specialty_{case_idx}", "General Practice")
                            if docx_key in st.session_state:
                                ok, msg = letter_generator.send_letter_email(
                                    to_email=_doc_obj.get("email", ""),
                                    subject=(
                                        f"[GP Triage] Referral Letter — "
                                        f"{triage_lvl} — {_spec}"
                                    ),
                                    body=(
                                        f"Dear {_doc_obj['name']},\n\n"
                                        f"Please find attached the referral letter "
                                        f"for a {triage_lvl} patient.\n\n"
                                        f"— GP Triage System"
                                    ),
                                    docx_bytes=st.session_state[docx_key],
                                    filename=f"referral_letter_{_date_slug}.docx",
                                )
                            else:
                                ok, msg = _send_assignment_email(
                                    doctor=_doc_obj,
                                    patient_input=entry["input"],
                                    triage_decision=triage_lvl,
                                    urgency=urgency_txt,
                                    specialty=_spec,
                                )
                            st.success(msg) if ok else st.warning(msg)

                    # Plain-text preview (collapsible)
                    if letter_key in st.session_state:
                        with st.expander("Preview letter text"):
                            st.text_area(
                                "Referral Letter (plain text):",
                                value=st.session_state[letter_key],
                                height=300,
                                key=f"letter_display_{case_idx}",
                                disabled=True,
                            )
                else:
                    st.info(
                        "No referral letter yet. "
                        "Go to the **Assign & Refer** tab and click "
                        "'Generate Referral Letter (.docx)'."
                    )

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
                                "patient_input": entry["input"],
                                "result": export_result,
                            },
                            indent=2,
                        ),
                        file_name=f"triage_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json",
                        key=f"dl_json_{case_idx}",
                    )
                with e2:
                    csv_data = (
                        f"Triage,{result['triage_decision']}\n"
                        f"Urgency,{result['urgency_timeframe']}\n"
                        f"Confidence,{result['confidence']}\n\n"
                        f"Patient Input:\n{entry['input']}\n\n"
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
                        key=f"dl_csv_{case_idx}",
                    )

                st.markdown("---")
                st.subheader("Print Summary")
                _specialty_val = st.session_state.get(f"specialty_{case_idx}", "Not assigned")
                _doc_obj       = st.session_state.get(f"selected_doctor_obj_{case_idx}", _DOCTORS[0])
                _imaging_val   = st.session_state.get(f"imaging_{case_idx}", [])
                _bloods_val    = st.session_state.get(f"bloods_{case_idx}", [])
                summary_lines = [
                    f"GP Triage Summary — {entry['timestamp'][:19].replace('T', ' ')}",
                    "=" * 60,
                    f"Patient Presentation : {entry['input']}",
                    f"Triage Decision      : {triage_lvl}",
                    f"Urgency              : {urgency_txt}",
                    f"Waiting Time         : {_WAITING_TIMES.get(triage_lvl, 'N/A')}",
                    f"Confidence           : {result.get('confidence', 'N/A')}",
                    f"Specialty Assigned   : {_specialty_val}",
                    f"Doctor Assigned      : {_doc_obj['name']} ({_doc_obj['role']}, {_doc_obj['site']})",
                    f"Imaging Requested    : {', '.join(_imaging_val) if _imaging_val else 'None'}",
                    f"Blood Tests          : {', '.join(_bloods_val) if _bloods_val else 'None'}",
                    "",
                    "Clinical Reasoning:",
                    result.get("clinical_reasoning", ""),
                    "",
                    "Red Flags:",
                    result.get("red_flags", ""),
                ]
                summary_text = "\n".join(summary_lines)
                st.text_area(
                    "Summary (copy or print from here):",
                    value=summary_text,
                    height=280,
                    key=f"print_summary_{case_idx}",
                )
                st.download_button(
                    label="Download Summary as .txt",
                    data=summary_text,
                    file_name=f"triage_summary_{entry['timestamp'][:10]}.txt",
                    mime="text/plain",
                    key=f"dl_summary_{case_idx}",
                )

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
