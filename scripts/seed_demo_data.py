"""
scripts/seed_demo_data.py -- Insert 5 complete demo patient journeys.

Run from project root:
    python scripts/seed_demo_data.py

Safe to re-run -- existing records are skipped via ON CONFLICT.
All output is ASCII-only (Windows-compatible console).

Works with both PostgreSQL (Supabase) and SQLite fallback.
DATABASE_URL is read from .env via python-dotenv.
"""
import sys
from pathlib import Path

# Ensure project root is on the path so src.database resolves correctly
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from sqlalchemy import text

from src.database import (
    _conn,
    init_db,
    save_patient,
    save_triage,
    save_assignment,
    save_referral,
    save_pathway_stage,
    save_audit,
    save_ward_log,
    save_observation,
    save_medication,
    save_safeguarding_flag,
    update_discharge_checklist,
    save_consultation,
    save_test_order,
    update_test_result,
    save_hospital_admission,
    save_discharge_summary,
    save_case_closure,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STAGE_LABELS = {
    1:  "Presentation",
    2:  "AI Triage",
    3:  "GP Consultation",
    4:  "Test Orders",
    5:  "Referral",
    6:  "Hospital Admission",
    7:  "Discharge Summary",
    8:  "Outcome & Follow-up",
    9:  "Community Care",
    10: "Case Closure",
}


def _stage(nhs: str, num: int, data: dict, status: str = "complete",
           updated_by: str = "system") -> None:
    save_pathway_stage(nhs, num, STAGE_LABELS[num], status, data, updated_by)


def _already_seeded(nhs: str) -> bool:
    """Return True if this NHS number already has a patient row."""
    with _conn() as conn:
        row = conn.execute(
            text("SELECT id FROM patients WHERE nhs_number = :nhs"), {"nhs": nhs}
        ).fetchone()
    return row is not None


def _gp_workflow_seeded(nhs: str) -> bool:
    """Return True if GP consultation records already exist for this patient."""
    with _conn() as conn:
        row = conn.execute(
            text("SELECT id FROM gp_consultations WHERE nhs_number = :nhs LIMIT 1"),
            {"nhs": nhs},
        ).fetchone()
    return row is not None


def update_pathway_stage_labels() -> None:
    """Update stage_name in pathway_stages to match the new 10-stage GP pathway.

    Safe to run repeatedly -- uses ON CONFLICT DO UPDATE via save_pathway_stage.
    Only updates the label; preserves existing status and data.
    """
    with _conn() as conn:
        rows = conn.execute(
            text("SELECT nhs_number, stage_number, status, stage_data, updated_by "
                 "FROM pathway_stages")
        ).fetchall()

    import json as _json
    for row in rows:
        nhs, snum, status, data_raw, updated_by = (
            row[0], row[1], row[2], row[3], row[4]
        )
        new_label = STAGE_LABELS.get(snum)
        if new_label:
            try:
                data = _json.loads(data_raw or "{}")
            except Exception:
                data = {}
            save_pathway_stage(nhs, snum, new_label, status, data, updated_by or "system")

    print("[OK] Pathway stage labels updated to new 10-stage GP pathway.")


# ---------------------------------------------------------------------------
# Patient 1: Dennis E, 58M -- RED Chest Pain -> Acute MI -> PCI -> Discharged
# ---------------------------------------------------------------------------

def seed_patient_1() -> None:
    nhs = "486 740 1692"
    if _already_seeded(nhs):
        print("[SKIP] Patient 1 already exists: " + nhs)
        return

    description = (
        "58-year-old male presenting with severe crushing chest pain radiating "
        "to the left arm, onset 45 minutes ago. Diaphoresis, nausea, and "
        "shortness of breath. History of hypertension and hypercholesterolaemia."
    )
    save_patient(nhs, age="58", gender="Male", description=description)

    save_triage(nhs, {
        "triage_decision":   "RED",
        "urgency_timeframe": "Immediate -- see within 0-15 minutes",
        "clinical_reasoning": (
            "Classic presentation of ST-elevation myocardial infarction (STEMI). "
            "Diaphoresis and radiation pattern indicate high-acuity cardiac event. "
            "Immediate cardiology activation required."
        ),
        "red_flags":         "Crushing chest pain, diaphoresis, left arm radiation, hypotension",
        "confidence":        "High confidence -- classic STEMI presentation",
        "nice_guideline":    "NICE NG185: Acute coronary syndromes",
        "recommended_action": "Activate cath lab, aspirin 300mg, GTN, IV access, 12-lead ECG",
        "differentials":     "STEMI, NSTEMI, Aortic dissection, Pulmonary embolism",
    }, response_time=2.8)

    save_assignment(nhs, "Dr. D. Wake-Trent", "Cardiology", "East Surrey Hospital")
    save_referral(nhs, "imaging",    "Chest X-Ray",         "IMMEDIATE", "East Surrey Hospital Radiology")
    save_referral(nhs, "imaging",    "Echocardiogram",      "URGENT",    "East Surrey Hospital Radiology")
    save_referral(nhs, "blood_test", "Troponin",            "IMMEDIATE", "East Surrey Hospital Pathology")
    save_referral(nhs, "blood_test", "FBC (Full Blood Count)", "IMMEDIATE", "East Surrey Hospital Pathology")

    _stage(nhs, 1, {
        "patient_description": description,
        "presentation_time":   "2026-04-08T09:12:00",
    }, updated_by="Reception")

    _stage(nhs, 2, {
        "ai_decision":  "RED",
        "urgency":      "Immediate -- see within 0-15 minutes",
        "confidence":   "High confidence -- classic STEMI presentation",
        "response_time_s": 2.8,
    }, updated_by="AI System")

    _stage(nhs, 3, {
        "assigned_doctor": "Dr. D. Wake-Trent",
        "specialty":       "Cardiology",
        "site":            "East Surrey Hospital",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 4, {
        "imaging":          ["Chest X-Ray", "Echocardiogram", "CT Chest / PE Protocol"],
        "blood_tests":      ["Troponin", "FBC (Full Blood Count)", "D-Dimer", "Lactate"],
        "letter_generated": True,
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 5, {
        "admission_date":       "2026-04-08",
        "ward_name":            "Coronary Care Unit",
        "bed_number":           "CCU-4",
        "admitting_consultant": "Dr. D. Wake-Trent -- Cardiologist",
        "admission_type":       "Emergency",
        "hospital":             "East Surrey Hospital",
        "admission_status":     "Admitted",
    }, updated_by="Dr. D. Wake-Trent")

    _stage(nhs, 6, {
        "confirmed_diagnosis":   "Acute ST-Elevation Myocardial Infarction",
        "icd10_code":            "I21.0 -- Acute transmural MI of anterior wall",
        "snomed_code":           "57054005",
        "diagnosing_consultant": "Dr. D. Wake-Trent -- Cardiologist",
        "diagnosis_date":        "2026-04-08",
        "diagnosis_status":      "Confirmed",
    }, updated_by="Dr. D. Wake-Trent")

    _stage(nhs, 7, {
        "treatment_type":    "Surgical",
        "procedure_name":    "Percutaneous Coronary Intervention (PCI) -- LAD stenting",
        "theatre":           "Cath Lab 1, East Surrey Hospital",
        "anaesthetic_type":  "Local",
        "operating_surgeon": "Dr. D. Wake-Trent -- Cardiologist",
        "procedure_date":    "2026-04-08",
        "duration_minutes":  75,
        "treatment_status":  "Complete",
    }, updated_by="Dr. D. Wake-Trent")

    _stage(nhs, 8, {
        "outcome":           "Successful",
        "complications":     "None",
        "length_of_stay":    "5 days",
        "follow_up_required": "Yes",
        "outcome_notes":     "TIMI 3 flow restored. EF 45% post-PCI. Haemodynamically stable.",
    }, updated_by="Dr. D. Wake-Trent")

    _stage(nhs, 9, {
        "followup_date":         "2026-05-13",
        "followup_location":     "East Surrey Hospital Cardiology Outpatients",
        "followup_doctor":       "Dr. D. Wake-Trent -- Cardiologist",
        "medications":           "Aspirin 75mg OD, Ticagrelor 90mg BD, Atorvastatin 80mg ON, Ramipril 5mg OD, Bisoprolol 2.5mg OD",
        "aftercare_instructions": "Cardiac rehab referral made. No driving for 4 weeks. Gradual return to activity.",
        "community_referrals":   ["Physiotherapy"],
        "aftercare_status":      "Complete",
    }, updated_by="Dr. D. Wake-Trent")

    _stage(nhs, 10, {
        "discharge_date":        "2026-04-13",
        "discharge_type":        "Home",
        "discharge_summary":     "Patient discharged home following successful PCI to LAD. TIMI 3 flow restored. On dual antiplatelet therapy. Cardiac rehab referral made. Follow-up in 4 weeks.",
        "gp_notified":           True,
        "gp_letter_generated":   True,
        "patient_accompanied":   True,
        "transport_arranged":    True,
        "discharge_medications": "Aspirin 75mg OD, Ticagrelor 90mg BD, Atorvastatin 80mg ON, Ramipril 5mg OD, Bisoprolol 2.5mg OD",
        "discharge_status":      "Discharged",
    }, updated_by="Dr. D. Wake-Trent")

    save_audit(nhs, "TRIAGE",    "RED triage decision. STEMI pathway activated.",            "AI System")
    save_audit(nhs, "ADMISSION", "Emergency admission to CCU.",                              "Dr. D. Wake-Trent")
    save_audit(nhs, "PROCEDURE", "PCI LAD stenting completed successfully.",                 "Dr. D. Wake-Trent")
    save_audit(nhs, "DISCHARGE", "Patient discharged home day 5. GP notification sent.",     "Dr. D. Wake-Trent")

    print("[OK] Patient 1 seeded: Dennis E -- Acute MI -- Discharged")


# ---------------------------------------------------------------------------
# Patient 2: Child, 8F -- RED Paediatric Fever -> Bacterial Meningitis -> IV Abx -> Discharged
# ---------------------------------------------------------------------------

def seed_patient_2() -> None:
    nhs = "375 819 2048"
    if _already_seeded(nhs):
        print("[SKIP] Patient 2 already exists: " + nhs)
        return

    description = (
        "8-year-old female presenting with high fever (39.8 C), severe headache, "
        "neck stiffness, photophobia, and non-blanching petechial rash on trunk. "
        "Accompanied by parent. Onset 6 hours ago."
    )
    save_patient(nhs, age="8", gender="Female", description=description)

    save_triage(nhs, {
        "triage_decision":   "RED",
        "urgency_timeframe": "Immediate -- see within 0-15 minutes",
        "clinical_reasoning": (
            "Non-blanching petechial rash with fever, neck stiffness, and photophobia "
            "is a medical emergency. Meningococcal septicaemia must be excluded immediately. "
            "NICE guideline NG51 mandates immediate parenteral antibiotics."
        ),
        "red_flags":         "Non-blanching rash, neck stiffness, photophobia, high fever",
        "confidence":        "High confidence -- meningitis red flag criteria met",
        "nice_guideline":    "NICE NG51: Meningitis (bacterial) and meningococcal septicaemia",
        "recommended_action": "IV Ceftriaxone immediately, blood cultures, LP if safe, ITU review",
        "differentials":     "Bacterial meningitis, Viral meningitis, Meningococcal sepsis, HSP",
    }, response_time=3.1)

    save_assignment(nhs, "Dr. A. Patel", "Paediatrics", "East Surrey Hospital")
    save_referral(nhs, "imaging",    "CT Head (non-contrast)", "IMMEDIATE", "East Surrey Hospital Radiology")
    save_referral(nhs, "blood_test", "Blood Cultures",         "IMMEDIATE", "East Surrey Hospital Pathology")
    save_referral(nhs, "blood_test", "FBC (Full Blood Count)", "IMMEDIATE", "East Surrey Hospital Pathology")
    save_referral(nhs, "blood_test", "CRP / ESR",              "IMMEDIATE", "East Surrey Hospital Pathology")

    _stage(nhs, 1, {
        "patient_description": description,
        "presentation_time":   "2026-04-06T14:22:00",
    }, updated_by="Reception")

    _stage(nhs, 2, {
        "ai_decision":  "RED",
        "urgency":      "Immediate -- see within 0-15 minutes",
        "confidence":   "High confidence -- meningitis red flag criteria met",
        "response_time_s": 3.1,
    }, updated_by="AI System")

    _stage(nhs, 3, {
        "assigned_doctor": "Dr. A. Patel",
        "specialty":       "Paediatrics",
        "site":            "East Surrey Hospital",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 4, {
        "imaging":          ["CT Head (non-contrast)"],
        "blood_tests":      ["FBC (Full Blood Count)", "CRP / ESR", "Blood Cultures", "Lactate"],
        "letter_generated": True,
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 5, {
        "admission_date":       "2026-04-06",
        "ward_name":            "Paediatric HDU",
        "bed_number":           "PHDU-2",
        "admitting_consultant": "Dr. A. Patel -- Paediatrician",
        "admission_type":       "Emergency",
        "hospital":             "East Surrey Hospital",
        "admission_status":     "Admitted",
    }, updated_by="Dr. A. Patel")

    _stage(nhs, 6, {
        "confirmed_diagnosis":   "Bacterial Meningitis -- Meningococcal (Group B)",
        "icd10_code":            "G00.9 -- Bacterial meningitis, unspecified",
        "snomed_code":           "7772004",
        "diagnosing_consultant": "Dr. A. Patel -- Paediatrician",
        "diagnosis_date":        "2026-04-06",
        "diagnosis_status":      "Confirmed",
    }, updated_by="Dr. A. Patel")

    _stage(nhs, 7, {
        "treatment_type":    "Medical",
        "procedure_name":    "IV Ceftriaxone 7-day course, Dexamethasone adjunct therapy",
        "theatre":           "Paediatric HDU",
        "anaesthetic_type":  "None",
        "operating_surgeon": "Dr. A. Patel -- Paediatrician",
        "procedure_date":    "2026-04-06",
        "duration_minutes":  0,
        "treatment_status":  "Complete",
    }, updated_by="Dr. A. Patel")

    _stage(nhs, 8, {
        "outcome":           "Successful",
        "complications":     "Mild hearing loss noted -- audiology referral made",
        "length_of_stay":    "7 days",
        "follow_up_required": "Yes",
        "outcome_notes":     "CSF cultures confirmed N. meningitidis Group B. Full neurological recovery. AAFB negative. Sensory deficit improving.",
    }, updated_by="Dr. A. Patel")

    _stage(nhs, 9, {
        "followup_date":         "2026-05-06",
        "followup_location":     "East Surrey Hospital Paediatric Outpatients",
        "followup_doctor":       "Dr. A. Patel -- Paediatrician",
        "medications":           "Oral Amoxicillin prophylaxis 5 days. Analgesia PRN.",
        "aftercare_instructions": "Rest at home for 2 weeks. School return after GP clearance. Monitor for hearing changes.",
        "community_referrals":   ["District Nurse", "Occupational Therapy"],
        "aftercare_status":      "Complete",
    }, updated_by="Dr. A. Patel")

    _stage(nhs, 10, {
        "discharge_date":        "2026-04-13",
        "discharge_type":        "Home",
        "discharge_summary":     "8-year-old female discharged after 7-day IV antibiotic course for confirmed bacterial meningitis. Good clinical recovery. Audiology follow-up arranged. Parent education given re: warning signs.",
        "gp_notified":           True,
        "gp_letter_generated":   True,
        "patient_accompanied":   True,
        "transport_arranged":    True,
        "discharge_medications": "Oral Amoxicillin prophylaxis x5 days, Paracetamol PRN",
        "discharge_status":      "Discharged",
    }, updated_by="Dr. A. Patel")

    save_audit(nhs, "TRIAGE",    "RED triage -- meningitis pathway activated immediately.", "AI System")
    save_audit(nhs, "ADMISSION", "Emergency paediatric HDU admission.",                    "Dr. A. Patel")
    save_audit(nhs, "TREATMENT", "IV Ceftriaxone commenced within 20 min of arrival.",     "Dr. A. Patel")
    save_audit(nhs, "DISCHARGE", "Discharged day 7. GP and audiology referral made.",      "Dr. A. Patel")

    print("[OK] Patient 2 seeded: Child 8F -- Bacterial Meningitis -- Discharged")


# ---------------------------------------------------------------------------
# Patient 3: Sarah M, 34F -- AMBER UTI/Pyelonephritis -> IV Abx -> Discharged
# ---------------------------------------------------------------------------

def seed_patient_3() -> None:
    nhs = "629 047 3815"
    if _already_seeded(nhs):
        print("[SKIP] Patient 3 already exists: " + nhs)
        return

    description = (
        "34-year-old female presenting with 4-day history of dysuria, frequency, "
        "right loin pain, fever (38.4 C), nausea and vomiting. Urinalysis: nitrites "
        "and leucocytes positive. Pregnancy test negative."
    )
    save_patient(nhs, age="34", gender="Female", description=description)

    save_triage(nhs, {
        "triage_decision":   "AMBER",
        "urgency_timeframe": "Urgent -- see within 1-2 hours",
        "clinical_reasoning": (
            "Clinical picture consistent with acute pyelonephritis: upper UTI symptoms "
            "with systemic upset and flank pain. IV antibiotics indicated given vomiting "
            "preventing oral therapy."
        ),
        "red_flags":         "Fever >38, rigors, flank pain, vomiting preventing oral antibiotics",
        "confidence":        "High confidence -- pyelonephritis criteria met",
        "nice_guideline":    "NICE NG112: Urinary tract infections in adults",
        "recommended_action": "IV co-amoxiclav, urine MC&S, blood cultures, renal USS",
        "differentials":     "Pyelonephritis, Renal calculi, Ovarian pathology, Appendicitis",
    }, response_time=2.4)

    save_assignment(nhs, "Dr. D. Ehiobu", "Urology", "Holmhurst Medical Centre")
    save_referral(nhs, "imaging",    "Ultrasound Abdomen",       "URGENT", "East Surrey Hospital Radiology")
    save_referral(nhs, "blood_test", "FBC (Full Blood Count)",   "URGENT", "East Surrey Hospital Pathology")
    save_referral(nhs, "blood_test", "U&E (Urea & Electrolytes)", "URGENT", "East Surrey Hospital Pathology")
    save_referral(nhs, "blood_test", "CRP / ESR",                "URGENT", "East Surrey Hospital Pathology")

    _stage(nhs, 1, {
        "patient_description": description,
        "presentation_time":   "2026-04-10T11:05:00",
    }, updated_by="Reception")

    _stage(nhs, 2, {
        "ai_decision":  "AMBER",
        "urgency":      "Urgent -- see within 1-2 hours",
        "confidence":   "High confidence -- pyelonephritis criteria met",
        "response_time_s": 2.4,
    }, updated_by="AI System")

    _stage(nhs, 3, {
        "assigned_doctor": "Dr. D. Ehiobu",
        "specialty":       "Urology",
        "site":            "Holmhurst Medical Centre",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 4, {
        "imaging":          ["Ultrasound Abdomen", "Ultrasound Pelvis"],
        "blood_tests":      ["FBC (Full Blood Count)", "U&E (Urea & Electrolytes)", "CRP / ESR"],
        "letter_generated": True,
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 5, {
        "admission_date":       "2026-04-10",
        "ward_name":            "Medical Assessment Unit",
        "bed_number":           "MAU-7",
        "admitting_consultant": "Dr. D. Ehiobu -- GP",
        "admission_type":       "Emergency",
        "hospital":             "East Surrey Hospital",
        "admission_status":     "Admitted",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 6, {
        "confirmed_diagnosis":   "Acute Pyelonephritis",
        "icd10_code":            "N10 -- Acute tubulo-interstitial nephritis",
        "snomed_code":           "45816000",
        "diagnosing_consultant": "Dr. D. Ehiobu -- GP",
        "diagnosis_date":        "2026-04-10",
        "diagnosis_status":      "Confirmed",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 7, {
        "treatment_type":    "Medical",
        "procedure_name":    "IV Co-amoxiclav 3-day course, step-down to oral Augmentin",
        "theatre":           "MAU-7, East Surrey Hospital",
        "anaesthetic_type":  "None",
        "operating_surgeon": "Dr. D. Ehiobu -- GP",
        "procedure_date":    "2026-04-10",
        "duration_minutes":  0,
        "treatment_status":  "Complete",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 8, {
        "outcome":           "Successful",
        "complications":     "None",
        "length_of_stay":    "3 days",
        "follow_up_required": "Yes",
        "outcome_notes":     "Urine MC&S: E. coli sensitive to co-amoxiclav. Renal USS normal. CRP normalising at discharge.",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 9, {
        "followup_date":         "2026-04-24",
        "followup_location":     "Holmhurst Medical Centre",
        "followup_doctor":       "Dr. D. Ehiobu -- GP",
        "medications":           "Co-amoxiclav 625mg TDS x 7 days (oral step-down)",
        "aftercare_instructions": "Complete antibiotic course. Increase fluid intake. Return if symptoms worsen.",
        "community_referrals":   [],
        "aftercare_status":      "Complete",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 10, {
        "discharge_date":        "2026-04-13",
        "discharge_type":        "Home",
        "discharge_summary":     "34F discharged following successful treatment for acute pyelonephritis. Sensitivities confirmed E. coli. Step-down to oral antibiotics. Follow-up with GP in 2 weeks.",
        "gp_notified":           True,
        "gp_letter_generated":   True,
        "patient_accompanied":   False,
        "transport_arranged":    False,
        "discharge_medications": "Co-amoxiclav 625mg TDS x 7 days",
        "discharge_status":      "Discharged",
    }, updated_by="Dr. D. Ehiobu")

    save_audit(nhs, "TRIAGE",    "AMBER triage -- pyelonephritis pathway.",                "AI System")
    save_audit(nhs, "ADMISSION", "MAU admission for IV antibiotics.",                      "Dr. D. Ehiobu")
    save_audit(nhs, "DISCHARGE", "Discharged day 3 on oral step-down. GP follow-up made.", "Dr. D. Ehiobu")

    print("[OK] Patient 3 seeded: Sarah M -- Pyelonephritis -- Discharged")


# ---------------------------------------------------------------------------
# Patient 4: James K, 42M -- AMBER Mental Health Crisis -> Inpatient -> Aftercare (not discharged)
# ---------------------------------------------------------------------------

def seed_patient_4() -> None:
    nhs = "748 392 6017"
    if _already_seeded(nhs):
        print("[SKIP] Patient 4 already exists: " + nhs)
        return

    description = (
        "42-year-old male presenting with 3-week history of worsening low mood, "
        "social withdrawal, insomnia, poor appetite, and passive suicidal ideation "
        "(no active plan). History of depression. Not currently medicated."
    )
    save_patient(nhs, age="42", gender="Male", description=description)

    save_triage(nhs, {
        "triage_decision":   "AMBER",
        "urgency_timeframe": "Urgent -- see within 1-2 hours",
        "clinical_reasoning": (
            "Severe depressive episode with passive suicidal ideation. Risk assessment "
            "required urgently. Inpatient stabilisation likely needed given functional "
            "deterioration and history."
        ),
        "red_flags":         "Passive suicidal ideation, functional decline, not currently treated",
        "confidence":        "Medium confidence -- psychiatric assessment required",
        "nice_guideline":    "NICE NG222: Depression in adults",
        "recommended_action": "Urgent psychiatric review, safe messaging, social support assessment",
        "differentials":     "Severe depression, Bipolar disorder, Adjustment disorder",
    }, response_time=3.7)

    save_assignment(nhs, "Dr. S. Morrison", "Psychiatry", "Greystone House Surgery")
    save_referral(nhs, "blood_test", "TFTs (Thyroid Function)",      "ROUTINE", "East Surrey Hospital Pathology")
    save_referral(nhs, "blood_test", "FBC (Full Blood Count)",        "ROUTINE", "East Surrey Hospital Pathology")

    _stage(nhs, 1, {
        "patient_description": description,
        "presentation_time":   "2026-04-09T10:30:00",
    }, updated_by="Reception")

    _stage(nhs, 2, {
        "ai_decision":  "AMBER",
        "urgency":      "Urgent -- see within 1-2 hours",
        "confidence":   "Medium confidence -- psychiatric assessment required",
        "response_time_s": 3.7,
    }, updated_by="AI System")

    _stage(nhs, 3, {
        "assigned_doctor": "Dr. S. Morrison",
        "specialty":       "Psychiatry",
        "site":            "Greystone House Surgery",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 4, {
        "imaging":          [],
        "blood_tests":      ["TFTs (Thyroid Function)", "FBC (Full Blood Count)"],
        "letter_generated": True,
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 5, {
        "admission_date":       "2026-04-09",
        "ward_name":            "Psychiatric Assessment Unit",
        "bed_number":           "PAU-3",
        "admitting_consultant": "Dr. S. Morrison -- GP",
        "admission_type":       "Emergency",
        "hospital":             "East Surrey Hospital",
        "admission_status":     "Admitted",
    }, updated_by="Dr. S. Morrison")

    _stage(nhs, 6, {
        "confirmed_diagnosis":   "Severe Depressive Episode without Psychotic Features",
        "icd10_code":            "F32.2 -- Severe depressive episode without psychotic symptoms",
        "snomed_code":           "191601007",
        "diagnosing_consultant": "Dr. S. Morrison -- GP",
        "diagnosis_date":        "2026-04-10",
        "diagnosis_status":      "Confirmed",
    }, updated_by="Dr. S. Morrison")

    _stage(nhs, 7, {
        "treatment_type":    "Medical",
        "procedure_name":    "Inpatient psychiatric stabilisation. Sertraline titration. CBT referral.",
        "theatre":           "PAU Ward",
        "anaesthetic_type":  "None",
        "operating_surgeon": "Dr. S. Morrison -- GP",
        "procedure_date":    "2026-04-10",
        "duration_minutes":  0,
        "treatment_status":  "In Progress",
    }, updated_by="Dr. S. Morrison")

    _stage(nhs, 8, {
        "outcome":           "Ongoing",
        "complications":     "None",
        "length_of_stay":    "4 days (still admitted)",
        "follow_up_required": "Yes",
        "outcome_notes":     "Mood improving with medication. Risk reduced. CBT waitlist joined. CPN allocated.",
    }, updated_by="Dr. S. Morrison")

    _stage(nhs, 9, {
        "followup_date":         "2026-05-09",
        "followup_location":     "Greystone House Surgery",
        "followup_doctor":       "Dr. S. Morrison -- GP",
        "medications":           "Sertraline 50mg OD, Zopiclone 7.5mg ON (short course)",
        "aftercare_instructions": "Crisis plan in place. CPN weekly contact. Samaritans number provided.",
        "community_referrals":   ["Mental Health", "Social Services"],
        "aftercare_status":      "In Progress",
    }, updated_by="Dr. S. Morrison")

    # Stage 10 is pending -- patient not yet discharged
    save_pathway_stage(nhs, 10, "Discharge", "pending", {}, "system")

    save_audit(nhs, "TRIAGE",    "AMBER triage -- mental health crisis pathway.",           "AI System")
    save_audit(nhs, "ADMISSION", "Emergency psychiatric admission.",                        "Dr. S. Morrison")
    save_audit(nhs, "TREATMENT", "Sertraline commenced. CBT referral made. CPN allocated.", "Dr. S. Morrison")

    print("[OK] Patient 4 seeded: James K -- Severe Depression -- Still Admitted")


# ---------------------------------------------------------------------------
# Patient 5: Emma T, 28F -- GREEN Sore Throat -> GP Managed -> Same-day Discharge
# ---------------------------------------------------------------------------

def seed_patient_5() -> None:
    nhs = "513 826 4739"
    if _already_seeded(nhs):
        print("[SKIP] Patient 5 already exists: " + nhs)
        return

    description = (
        "28-year-old female presenting with 3-day history of sore throat, "
        "mild odynophagia, low-grade fever (37.6 C), and fatigue. "
        "No stridor, no drooling, no trismus. FeverPAIN score 2."
    )
    save_patient(nhs, age="28", gender="Female", description=description)

    save_triage(nhs, {
        "triage_decision":   "GREEN",
        "urgency_timeframe": "Routine -- see within 24-48 hours",
        "clinical_reasoning": (
            "Viral tonsillitis most likely given FeverPAIN score 2 and absence of "
            "bacterial features. No airway compromise. NICE recommends self-care "
            "with safety-net advice."
        ),
        "red_flags":         "None identified",
        "confidence":        "High confidence -- low-risk viral throat infection",
        "nice_guideline":    "NICE NG84: Sore throat (acute): antimicrobial prescribing",
        "recommended_action": "Analgesia, fluids, safety-net advice. No antibiotics indicated.",
        "differentials":     "Viral tonsillitis, Strep tonsillitis, EBV (glandular fever)",
    }, response_time=1.9)

    save_assignment(nhs, "Dr. D. Ehiobu", "General Practice", "Holmhurst Medical Centre")

    _stage(nhs, 1, {
        "patient_description": description,
        "presentation_time":   "2026-04-13T09:45:00",
    }, updated_by="Reception")

    _stage(nhs, 2, {
        "ai_decision":  "GREEN",
        "urgency":      "Routine -- see within 24-48 hours",
        "confidence":   "High confidence -- low-risk viral throat infection",
        "response_time_s": 1.9,
    }, updated_by="AI System")

    _stage(nhs, 3, {
        "assigned_doctor": "Dr. D. Ehiobu",
        "specialty":       "General Practice",
        "site":            "Holmhurst Medical Centre",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 4, {
        "imaging":          [],
        "blood_tests":      [],
        "letter_generated": False,
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 5, {
        "admission_date":       "2026-04-13",
        "ward_name":            "GP Consultation Room",
        "bed_number":           "N/A",
        "admitting_consultant": "Dr. D. Ehiobu -- GP",
        "admission_type":       "Day Case",
        "hospital":             "Holmhurst Medical Centre",
        "admission_status":     "Day case -- not admitted",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 6, {
        "confirmed_diagnosis":   "Acute Viral Tonsillitis",
        "icd10_code":            "J03.9 -- Acute tonsillitis, unspecified",
        "snomed_code":           "90176007",
        "diagnosing_consultant": "Dr. D. Ehiobu -- GP",
        "diagnosis_date":        "2026-04-13",
        "diagnosis_status":      "Confirmed",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 7, {
        "treatment_type":    "Conservative",
        "procedure_name":    "Symptomatic management: analgesia and fluids",
        "theatre":           "GP Consultation Room",
        "anaesthetic_type":  "None",
        "operating_surgeon": "Dr. D. Ehiobu -- GP",
        "procedure_date":    "2026-04-13",
        "duration_minutes":  0,
        "treatment_status":  "Complete",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 8, {
        "outcome":           "Successful",
        "complications":     "None",
        "length_of_stay":    "Same day",
        "follow_up_required": "No",
        "outcome_notes":     "Resolved with supportive management. No antibiotics required. Patient education provided.",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 9, {
        "followup_date":         "2026-04-20",
        "followup_location":     "Holmhurst Medical Centre (if not improving)",
        "followup_doctor":       "Dr. D. Ehiobu -- GP",
        "medications":           "Ibuprofen 400mg TDS PRN, Paracetamol 1g QDS PRN",
        "aftercare_instructions": "Rest for 2-3 days. Adequate hydration. Return if symptoms worsen or fever persists >5 days.",
        "community_referrals":   [],
        "aftercare_status":      "Complete",
    }, updated_by="Dr. D. Ehiobu")

    _stage(nhs, 10, {
        "discharge_date":        "2026-04-13",
        "discharge_type":        "Home",
        "discharge_summary":     "28F seen and discharged same day. Viral tonsillitis confirmed. Conservative management. Safety-net advice given. No follow-up required unless symptoms worsen.",
        "gp_notified":           False,
        "gp_letter_generated":   False,
        "patient_accompanied":   False,
        "transport_arranged":    False,
        "discharge_medications": "Ibuprofen 400mg TDS PRN, Paracetamol 1g QDS PRN",
        "discharge_status":      "Discharged",
    }, updated_by="Dr. D. Ehiobu")

    save_audit(nhs, "TRIAGE",    "GREEN triage -- viral tonsillitis. No escalation.", "AI System")
    save_audit(nhs, "DISCHARGE", "Same-day discharge. Conservative management.",       "Dr. D. Ehiobu")

    print("[OK] Patient 5 seeded: Emma T -- Viral Tonsillitis -- Same-day Discharge")


# ---------------------------------------------------------------------------
# Ward data: logs, observations, medications, safeguarding, checklists
# ---------------------------------------------------------------------------

def _ward_already_seeded(nhs: str) -> bool:
    """Return True if ward log entries already exist for this patient."""
    with _conn() as conn:
        row = conn.execute(
            text("SELECT id FROM ward_logs WHERE nhs_number=:nhs LIMIT 1"), {"nhs": nhs}
        ).fetchone()
    return row is not None


def _checklist_complete() -> dict:
    """Return a fully signed-off discharge checklist."""
    from datetime import datetime
    ts = datetime.now().isoformat()
    return {
        item: {"checked": True, "signed_by": "Dr. D. Ehiobu", "timestamp": ts}
        for item in [
            "summary_completed", "gp_letter_sent", "tto_prescribed",
            "followup_booked", "patient_understands", "meds_explained",
            "transport_arranged", "care_package", "social_services",
            "nok_informed", "accompanied", "equipment_provided", "community_nursing",
        ]
    }


def seed_ward_data() -> None:
    """Seed ward logs, observations, medications, safeguarding, checklists."""

    # ── Patient 1: Dennis E, 58M -- Acute MI post-PCI ─────────────────────
    nhs1 = "486 740 1692"
    if not _ward_already_seeded(nhs1):
        # Ward logs
        save_ward_log(nhs1, "2026-04-08", "Morning Round",
                      "Dr. D. Wake-Trent", "Consultant",
                      "Chest pain resolved post-PCI. Patient comfortable.",
                      "HR 72 reg. BP 118/74. Sinus rhythm on telemetry. No murmurs.",
                      "Post-PCI day 0. Haemodynamically stable. TIMI 3 flow restored.",
                      "Continue dual antiplatelet. Echo tomorrow. Cardiac rehab referral.")
        save_ward_log(nhs1, "2026-04-10", "Morning Round",
                      "Dr. D. Wake-Trent", "Consultant",
                      "Feeling much better. Walking to bathroom independently.",
                      "BP 124/76. HR 68. O2 sats 97% on air. Wound healing well.",
                      "Post-PCI day 2. Good recovery. Echo: EF 45%.",
                      "Continue meds. Plan discharge day 5 if remains stable.")
        save_ward_log(nhs1, "2026-04-12", "Morning Round",
                      "Dr. D. Wake-Trent", "Consultant",
                      "No chest pain. Anxious about going home.",
                      "Observations stable. Wound site clean.",
                      "Ready for discharge. Excellent progress.",
                      "Discharge tomorrow. TTOs prescribed. Cardiac rehab booked.")
        # Observations
        save_observation(nhs1, "2026-04-08 08:00", "Morning", "Nurse Garcia",
                         36.8, 118, 74, 72, 16, 98, "Alert", 2,
                         1200, 800, "Intact", "Normal", 1)
        save_observation(nhs1, "2026-04-10 08:00", "Morning", "Nurse Patel",
                         37.1, 124, 76, 68, 14, 97, "Alert", 1,
                         1500, 1100, "Intact", "Normal", 0)
        # Medications
        save_medication(nhs1, "2026-04-08 10:00", "Aspirin", "75mg", "Oral", "OD",
                        "Dr. D. Wake-Trent", "Nurse Garcia", "Given", "Post-PCI antiplatelet")
        save_medication(nhs1, "2026-04-08 10:00", "Ticagrelor", "90mg", "Oral", "BD",
                        "Dr. D. Wake-Trent", "Nurse Garcia", "Given", "Dual antiplatelet")
        save_medication(nhs1, "2026-04-08 10:00", "Atorvastatin", "80mg", "Oral", "OD",
                        "Dr. D. Wake-Trent", "Nurse Garcia", "Given", "High-intensity statin")
        # Discharge checklist
        update_discharge_checklist(nhs1, _checklist_complete(), "Dr. D. Wake-Trent")
        print("[OK] Ward data seeded: Patient 1 (Dennis E)")
    else:
        print("[SKIP] Ward data already seeded: Patient 1")

    # ── Patient 2: Child 8F -- Bacterial Meningitis ────────────────────────
    nhs2 = "375 819 2048"
    if not _ward_already_seeded(nhs2):
        save_ward_log(nhs2, "2026-04-06", "Morning Round",
                      "Dr. A. Patel", "Consultant",
                      "Child distressed. Parent present throughout. Non-blanching rash improving.",
                      "T 38.9. HR 118. RR 26. BP 88/52. Photophobic. Neck stiffness present.",
                      "Day 0 bacterial meningitis. IV Ceftriaxone started 20 min post-arrival.",
                      "Continue IV Ceftriaxone. Dexamethasone started. LP deferred -- too unwell.")
        save_ward_log(nhs2, "2026-04-09", "Morning Round",
                      "Dr. A. Patel", "Consultant",
                      "Less distressed. Taking oral fluids. Parent very anxious but reassured.",
                      "T 37.4. HR 94. RR 18. BP 102/64. Rash fading. Neck stiffness resolving.",
                      "Day 3 meningitis. Good clinical response to antibiotics.",
                      "Continue IV Abx day 4-7. Audiology referral made. CAHMS support offered.")
        save_ward_log(nhs2, "2026-04-12", "Morning Round",
                      "Dr. A. Patel", "Consultant",
                      "Well in herself. Playing with toys. Ready to go home.",
                      "Observations normal. Rash resolved. Neurologically intact.",
                      "Day 6. Full clinical recovery. Step down to oral antibiotics.",
                      "Discharge tomorrow. GP letter. Audiology follow-up in 4 weeks.")
        save_observation(nhs2, "2026-04-06 14:30", "Afternoon", "Nurse Thompson",
                         38.9, 88, 52, 118, 26, 94, "Alert", 7,
                         800, 300, "Intact", "Normal", 9)
        save_observation(nhs2, "2026-04-09 08:00", "Morning", "Nurse Thompson",
                         37.4, 102, 64, 94, 18, 98, "Alert", 3,
                         1200, 900, "Intact", "Normal", 2)
        save_medication(nhs2, "2026-04-06 14:00", "Ceftriaxone", "80mg/kg IV",
                        "IV", "OD", "Dr. A. Patel", "Nurse Thompson", "Given",
                        "IV -- bacterial meningitis")
        save_medication(nhs2, "2026-04-06 14:30", "Dexamethasone", "0.15mg/kg IV",
                        "IV", "QDS", "Dr. A. Patel", "Nurse Thompson", "Given",
                        "Adjunct therapy -- meningitis")
        # SAFEGUARDING FLAG: Child protection (safeguarding concern for child patient)
        save_safeguarding_flag(nhs2,
                               "Child protection concern",
                               "2026-04-07", "Dr. A. Patel",
                               "Child admitted with serious illness. Safeguarding review per protocol for all paediatric admissions. No active concern identified. Routine flag for documentation.",
                               "Named nurse safeguarding review completed. No further action required.",
                               "Surrey County Council Children's Services -- notification only",
                               "SCC-2026-04-0071")
        update_discharge_checklist(nhs2, _checklist_complete(), "Dr. A. Patel")
        print("[OK] Ward data seeded: Patient 2 (Child 8F)")
    else:
        print("[SKIP] Ward data already seeded: Patient 2")

    # ── Patient 3: Sarah M, 34F -- Pyelonephritis ─────────────────────────
    nhs3 = "629 047 3815"
    if not _ward_already_seeded(nhs3):
        save_ward_log(nhs3, "2026-04-10", "Morning Round",
                      "Dr. D. Ehiobu", "GP",
                      "Still nauseated. Right loin pain easing slightly. Tolerating sips.",
                      "T 38.4. HR 96. BP 108/70. RR 18. Loin tenderness +. MSU positive.",
                      "Day 0 pyelonephritis. IV co-amoxiclav started. E. coli on culture.",
                      "Continue IV antibiotics. MSU sent. IV fluids. Anti-emetics PRN.")
        save_ward_log(nhs3, "2026-04-12", "Morning Round",
                      "Dr. D. Ehiobu", "GP",
                      "Nausea resolved. Tolerating oral fluids and diet.",
                      "T 37.1. HR 78. BP 118/72. Loin tenderness much improved.",
                      "Day 2. Responding well. CRP falling.",
                      "Step down to oral co-amoxiclav. Plan discharge day 3.")
        save_observation(nhs3, "2026-04-10 09:00", "Morning", "Nurse Garcia",
                         38.4, 108, 70, 96, 18, 97, "Alert", 4,
                         1000, 400, "Intact", "Normal", 5)
        save_observation(nhs3, "2026-04-12 08:30", "Morning", "Nurse Garcia",
                         37.1, 118, 72, 78, 16, 99, "Alert", 1,
                         1400, 1200, "Intact", "Normal", 0)
        save_medication(nhs3, "2026-04-10 10:00", "Co-amoxiclav", "1.2g",
                        "IV", "TDS", "Dr. D. Ehiobu", "Nurse Garcia", "Given",
                        "IV for pyelonephritis -- E.coli sensitive")
        save_medication(nhs3, "2026-04-10 10:00", "Ondansetron", "4mg",
                        "IV", "PRN", "Dr. D. Ehiobu", "Nurse Garcia", "Given",
                        "Anti-emetic")
        update_discharge_checklist(nhs3, _checklist_complete(), "Dr. D. Ehiobu")
        print("[OK] Ward data seeded: Patient 3 (Sarah M)")
    else:
        print("[SKIP] Ward data already seeded: Patient 3")

    # ── Patient 4: James K, 42M -- Severe Depression (still admitted) ──────
    nhs4 = "748 392 6017"
    if not _ward_already_seeded(nhs4):
        save_ward_log(nhs4, "2026-04-09", "Morning Round",
                      "Dr. S. Morrison", "GP",
                      "Very low mood. Passive suicidal ideation. Denies plan. Accepting medication.",
                      "Alert and orientated. No psychotic features. PHQ-9 score 22 (severe).",
                      "Severe depressive episode. Risk assessed -- passive SI, no plan, no intent.",
                      "Commence Sertraline 50mg. 1:1 nursing observation. Crisis plan in place.")
        save_ward_log(nhs4, "2026-04-11", "Morning Round",
                      "Dr. S. Morrison", "GP",
                      "Mood slightly improved. Engaging with nursing staff. Eating more.",
                      "Alert. PHQ-9 score 18 (still severe). No SI today. Sleep improving.",
                      "Moderate improvement on day 3 Sertraline. Engaging with ward activities.",
                      "Continue Sertraline. CPN allocated. Social services referral made.")
        save_ward_log(nhs4, "2026-04-13", "Morning Round",
                      "Dr. S. Morrison", "GP",
                      "Reports feeling more hopeful. Engaged in CBT session. Wants to go home.",
                      "Alert, less agitated. PHQ-9 score 14. No active SI.",
                      "Significant improvement. Safe for discharge with robust care plan.",
                      "Plan discharge next 2 days. Crisis plan + CPN + GP follow-up.")
        save_observation(nhs4, "2026-04-09 09:00", "Morning", "Nurse Khan",
                         36.9, 126, 82, 88, 16, 99, "Alert", 5,
                         1000, 800, "Intact", "Normal", 0)
        save_observation(nhs4, "2026-04-11 09:00", "Morning", "Nurse Khan",
                         37.0, 122, 78, 74, 15, 99, "Alert", 3,
                         1200, 950, "Intact", "Normal", 0)
        save_medication(nhs4, "2026-04-09 20:00", "Sertraline", "50mg",
                        "Oral", "OD", "Dr. S. Morrison", "Nurse Khan", "Given",
                        "Antidepressant -- SSRI")
        save_medication(nhs4, "2026-04-09 22:00", "Zopiclone", "7.5mg",
                        "Oral", "OD", "Dr. S. Morrison", "Nurse Khan", "Given",
                        "Short course -- insomnia. Max 2 weeks.")
        # Adult safeguarding flag (mental capacity concern)
        save_safeguarding_flag(nhs4,
                               "Mental capacity concern (MCA assessment needed)",
                               "2026-04-09", "Dr. S. Morrison",
                               "Patient admitted with severe depression and passive suicidal ideation. MCA assessment completed -- patient has capacity to consent/refuse treatment.",
                               "Formal MCA assessment documented. Patient consented to all treatments. Crisis plan co-produced with patient.",
                               "No external referral required",
                               "MCA-2026-04-011")
        # No complete discharge checklist for patient 4 (not yet discharged)
        print("[OK] Ward data seeded: Patient 4 (James K)")
    else:
        print("[SKIP] Ward data already seeded: Patient 4")

    # ── Patient 5: Emma T, 28F -- Viral Tonsillitis (same-day) ───────────
    nhs5 = "513 826 4739"
    if not _ward_already_seeded(nhs5):
        save_ward_log(nhs5, "2026-04-13", "Morning Round",
                      "Dr. D. Ehiobu", "GP",
                      "Sore throat 3 days. Mild odynophagia. Low-grade fever. No stridor.",
                      "T 37.6. Tonsils mildly inflamed -- no exudate. No lymphadenopathy. FeverPAIN 2.",
                      "Viral tonsillitis -- no bacterial features. Antibiotics not indicated.",
                      "Analgesia PRN. Fluids. Safety-net advice. Discharge same day.")
        save_observation(nhs5, "2026-04-13 10:00", "Morning", "Nurse Garcia",
                         37.6, 116, 74, 76, 14, 99, "Alert", 2,
                         0, 0, "Intact", "Normal", 0)
        save_medication(nhs5, "2026-04-13 10:30", "Ibuprofen", "400mg",
                        "Oral", "TDS", "Dr. D. Ehiobu", "Dr. D. Ehiobu", "Given",
                        "PRN analgesia -- viral tonsillitis")
        save_medication(nhs5, "2026-04-13 10:30", "Paracetamol", "1g",
                        "Oral", "QDS", "Dr. D. Ehiobu", "Dr. D. Ehiobu", "Given",
                        "PRN analgesia")
        update_discharge_checklist(nhs5, _checklist_complete(), "Dr. D. Ehiobu")
        print("[OK] Ward data seeded: Patient 5 (Emma T)")
    else:
        print("[SKIP] Ward data already seeded: Patient 5")


# ---------------------------------------------------------------------------
# GP workflow data: consultations, test orders, admissions, discharge summaries,
# case closures -- for all 5 demo patients.
# ---------------------------------------------------------------------------

def seed_gp_workflow_data() -> None:
    """Insert GP consultation, test order, hospital admission, discharge summary,
    and case closure records for all 5 demo patients.

    Skips any patient whose GP consultation records already exist.
    """

    # ── Patient 1: Dennis E, 58M -- RED Chest Pain -> STEMI -> PCI -> Discharged ─
    nhs1 = "486 740 1692"
    if _gp_workflow_seeded(nhs1):
        print("[SKIP] GP workflow already seeded: Patient 1")
    else:
        # GP Consultation -- initial presentation
        cid1 = save_consultation(
            nhs_number=nhs1,
            consultation_date="2026-04-08",
            gp_name="Dr. D. Ehiobu",
            gp_email="d.ehiobu@holmhurst.nhs.uk",
            presenting_complaint=(
                "58-year-old male with severe crushing chest pain radiating to "
                "the left arm, onset 45 minutes ago. Diaphoresis and nausea."
            ),
            examination_findings=(
                "Patient diaphoretic, pale, in obvious distress. "
                "HR 102 bpm irregular. BP 94/60. RR 22. SpO2 94% on air. "
                "Temp 36.8. 12-lead ECG: ST elevation in leads V1-V4."
            ),
            assessment=(
                "ST-elevation myocardial infarction (STEMI) -- anterior wall. "
                "High acuity cardiac emergency. NICE NG185 pathway activated."
            ),
            plan="999 called immediately. Aspirin 300mg given. GTN 0.4mg sublingual. "
                 "IV access established. Cath lab at East Surrey activated.",
            plan_detail=(
                "Patient transferred by blue-light ambulance to East Surrey Hospital "
                "Cardiology. Dr. D. Wake-Trent (Cardiologist) alerted."
            ),
            follow_up_date="2026-05-13",
            follow_up_gp="Dr. D. Ehiobu",
            follow_up_surgery="Holmhurst Medical Centre",
            created_by="Dr. D. Ehiobu",
        )

        # Test orders
        t1a = save_test_order(nhs1, "Troponin I", "blood_test", "2026-04-08",
                              "Dr. D. Ehiobu", consultation_id=cid1, notify_nhs_app=True)
        update_test_result(t1a, "2026-04-08", "Troponin I: 4.82 ng/mL (ref <0.04) -- markedly elevated",
                           "abnormal", "Confirms acute MI. Cath lab activated.",
                           "Emergency transfer to East Surrey Cardiology.")

        t1b = save_test_order(nhs1, "FBC (Full Blood Count)", "blood_test", "2026-04-08",
                              "Dr. D. Ehiobu", consultation_id=cid1)
        update_test_result(t1b, "2026-04-08", "Hb 14.2, WBC 11.3, Plt 198 -- mildly elevated WBC",
                           "abnormal", "Stress response expected in acute MI.", "No additional action.")

        t1c = save_test_order(nhs1, "Chest X-Ray", "imaging", "2026-04-08",
                              "Dr. D. Wake-Trent", consultation_id=cid1)
        update_test_result(t1c, "2026-04-08", "CXR: Mild pulmonary oedema. No pneumothorax.",
                           "abnormal", "Consistent with LV dysfunction post-MI.", "Echo arranged.")

        t1d = save_test_order(nhs1, "Echocardiogram", "imaging", "2026-04-09",
                              "Dr. D. Wake-Trent", consultation_id=cid1)
        update_test_result(t1d, "2026-04-09", "Echo: LVEF 45%. Anterior wall hypokinesis. No pericardial effusion.",
                           "abnormal", "Post-PCI echo. Acceptable EF for anterior STEMI.",
                           "Cardiac rehab referral made. Repeat echo in 3 months.")

        # Hospital admission
        adm1 = save_hospital_admission(
            nhs_number=nhs1,
            admission_date="2026-04-08",
            hospital_name="East Surrey Hospital",
            ward="Coronary Care Unit (CCU-4)",
            consultant="Dr. D. Wake-Trent -- Cardiologist",
            diagnosis="Acute ST-Elevation Myocardial Infarction (I21.0)",
            treatment="Percutaneous Coronary Intervention (PCI) -- LAD stenting. "
                      "Dual antiplatelet therapy. High-intensity statin.",
            complications="None",
            expected_discharge="2026-04-13",
        )

        # Discharge summary
        save_discharge_summary(
            nhs_number=nhs1,
            discharge_date="2026-04-13",
            discharge_destination="Home",
            admission_id=adm1,
            diagnosis="Acute anterior STEMI -- LAD occlusion. TIMI 0 flow on admission, TIMI 3 post-PCI.",
            treatment_given=(
                "Primary PCI to LAD with drug-eluting stent (DES). "
                "Dual antiplatelet therapy (aspirin + ticagrelor). "
                "Atorvastatin 80mg, Ramipril 5mg, Bisoprolol 2.5mg commenced."
            ),
            discharge_medications=(
                "Aspirin 75mg OD, Ticagrelor 90mg BD, Atorvastatin 80mg ON, "
                "Ramipril 5mg OD, Bisoprolol 2.5mg OD"
            ),
            follow_up_instructions=(
                "Cardiology OPD 4 weeks (2026-05-13). Cardiac rehabilitation referral made. "
                "No driving for 4 weeks (DVLA standard post-MI). "
                "Return immediately if chest pain, SOB, or palpitations."
            ),
            gp_actions=(
                "1. Blood pressure and lipid review at 6-week follow-up. "
                "2. Continue dual antiplatelet -- do not stop without cardiology advice. "
                "3. Repeat echo report to be filed when received (booked 2026-07-13). "
                "4. Cardiac rehab attendance to be confirmed."
            ),
        )

        # Case closure
        save_case_closure(
            nhs_number=nhs1,
            closed_by="Dr. D. Ehiobu",
            closure_reason="Discharge following successful PCI. GP follow-up plan in place.",
            retention_date="2036-04-13",
            case_summary=(
                "58M with anterior STEMI. Primary PCI to LAD performed 2026-04-08. "
                "TIMI 3 flow restored. EF 45% post-procedure. Discharged day 5 on DAPT. "
                "Cardiac rehab referral made. GP to review at 6 weeks."
            ),
        )

        print("[OK] GP workflow seeded: Patient 1 (Dennis E -- STEMI)")

    # ── Patient 2: Child 8F -- RED Meningitis -> IV Abx -> Discharged ─────────
    nhs2 = "375 819 2048"
    if _gp_workflow_seeded(nhs2):
        print("[SKIP] GP workflow already seeded: Patient 2")
    else:
        cid2 = save_consultation(
            nhs_number=nhs2,
            consultation_date="2026-04-06",
            gp_name="Dr. A. Patel",
            gp_email="a.patel@eastsurrey.nhs.uk",
            presenting_complaint=(
                "8-year-old female with 6-hour history of high fever (39.8C), "
                "severe headache, neck stiffness, photophobia, and non-blanching "
                "petechial rash on trunk. Accompanied by parent."
            ),
            examination_findings=(
                "T 39.8. HR 118. RR 26. BP 88/52. SpO2 94%. Kernig sign positive. "
                "Brudzinski sign positive. Non-blanching purpuric rash on trunk and thighs. "
                "Photophobic. GCS 14/15 (E3V5M6)."
            ),
            assessment=(
                "Bacterial meningitis / meningococcal septicaemia. "
                "NICE NG51 red flag criteria fully met. Medical emergency."
            ),
            plan=(
                "IV Ceftriaxone 80mg/kg stat commenced. Blood cultures before antibiotics. "
                "Dexamethasone 0.15mg/kg IV commenced. ITU reviewed -- HDU level care. "
                "CT head arranged to assess for LP safety."
            ),
            plan_detail=(
                "Parent kept at bedside. PHE notified re: meningococcal case. "
                "Siblings and close contacts assessed for prophylaxis."
            ),
            follow_up_date="2026-05-06",
            follow_up_gp="Dr. A. Patel",
            follow_up_surgery="East Surrey Hospital Paediatric Outpatients",
            created_by="Dr. A. Patel",
        )

        t2a = save_test_order(nhs2, "Blood Cultures", "microbiology", "2026-04-06",
                              "Dr. A. Patel", consultation_id=cid2)
        update_test_result(t2a, "2026-04-07",
                           "N. meningitidis Group B isolated. Sensitive to ceftriaxone.",
                           "abnormal", "Culture confirms meningococcal disease Group B.",
                           "Continue IV Ceftriaxone. PHE notification completed.")

        t2b = save_test_order(nhs2, "FBC (Full Blood Count)", "blood_test", "2026-04-06",
                              "Dr. A. Patel", consultation_id=cid2)
        update_test_result(t2b, "2026-04-06",
                           "WBC 19.4 (neutrophilia), Hb 11.8, Plt 88 -- thrombocytopenia",
                           "abnormal", "Consistent with bacterial sepsis.",
                           "Monitor platelet trend. Haematology review if worsening.")

        t2c = save_test_order(nhs2, "CRP / ESR", "blood_test", "2026-04-06",
                              "Dr. A. Patel", consultation_id=cid2)
        update_test_result(t2c, "2026-04-06", "CRP 218 mg/L (ref <5). ESR 94.",
                           "abnormal", "Severe inflammatory response. Expected in bacterial meningitis.",
                           "Repeat CRP day 3.")

        t2d = save_test_order(nhs2, "CT Head (non-contrast)", "imaging", "2026-04-06",
                              "Dr. A. Patel", consultation_id=cid2)
        update_test_result(t2d, "2026-04-06",
                           "CT head: No midline shift. No hydrocephalus. No mass lesion. Safe for LP.",
                           "normal", "LP deferred -- patient too unwell on day 0.",
                           "Re-assess LP suitability day 2-3.")

        adm2 = save_hospital_admission(
            nhs_number=nhs2,
            admission_date="2026-04-06",
            hospital_name="East Surrey Hospital",
            ward="Paediatric HDU (PHDU-2)",
            consultant="Dr. A. Patel -- Paediatrician",
            diagnosis="Bacterial Meningitis -- N. meningitidis Group B (G00.9)",
            treatment="IV Ceftriaxone 7-day course. IV Dexamethasone adjunct. "
                      "Supportive care: IV fluids, analgesia, antipyretics.",
            complications="Mild bilateral sensorineural hearing loss -- audiology referral made.",
            expected_discharge="2026-04-13",
        )

        save_discharge_summary(
            nhs_number=nhs2,
            discharge_date="2026-04-13",
            discharge_destination="Home",
            admission_id=adm2,
            diagnosis=(
                "Confirmed bacterial meningitis -- Neisseria meningitidis Group B. "
                "CSF: cloudy, WBC 2,400, protein 3.8 g/L, glucose 1.1 (blood 6.2)."
            ),
            treatment_given=(
                "IV Ceftriaxone 80mg/kg OD for 7 days. "
                "IV Dexamethasone 0.15mg/kg QDS for 4 days. "
                "IV fluids, strict I/O monitoring, barrier nursing."
            ),
            discharge_medications="Oral Amoxicillin prophylaxis x5 days. Paracetamol PRN.",
            follow_up_instructions=(
                "Audiology assessment in 4 weeks (2026-05-13). "
                "Paediatric OPD follow-up 2026-05-06. "
                "Return immediately if fever, headache, or rash recurs."
            ),
            gp_actions=(
                "1. Confirm audiology appointment received. "
                "2. School return: GP clearance required -- minimum 2 weeks rest. "
                "3. Monitor siblings for symptoms -- prophylactic Rifampicin course completed. "
                "4. File PHE meningococcal notification (reference PHE-2026-04-0412)."
            ),
        )

        save_case_closure(
            nhs_number=nhs2,
            closed_by="Dr. A. Patel",
            closure_reason="Discharge following recovery from bacterial meningitis.",
            retention_date="2033-04-06",  # Child: 25th birthday (2018 + 25 = 2043 vs 10yr = 2036; 2043 wins; but DOB unknown so 10yr used)
            case_summary=(
                "8F with bacterial meningitis (N. meningitidis Group B). "
                "Presented with classic triad and non-blanching rash. IV Ceftriaxone 7 days. "
                "Full neurological recovery. Mild bilateral hearing loss -- audiology follow-up arranged. "
                "PHE notified. Siblings given chemoprophylaxis."
            ),
        )

        print("[OK] GP workflow seeded: Patient 2 (Child 8F -- Meningitis)")

    # ── Patient 3: Sarah M, 34F -- AMBER Pyelonephritis -> IV Abx -> Discharged ─
    nhs3 = "629 047 3815"
    if _gp_workflow_seeded(nhs3):
        print("[SKIP] GP workflow already seeded: Patient 3")
    else:
        cid3 = save_consultation(
            nhs_number=nhs3,
            consultation_date="2026-04-10",
            gp_name="Dr. D. Ehiobu",
            gp_email="d.ehiobu@holmhurst.nhs.uk",
            presenting_complaint=(
                "34-year-old female with 4-day history of dysuria, urinary frequency, "
                "right loin pain, fever (38.4C), nausea and vomiting. "
                "Urinalysis: nitrites+, leucocytes++. Pregnancy test negative."
            ),
            examination_findings=(
                "T 38.4. HR 96. BP 108/70. RR 18. SpO2 97%. "
                "Right CVA tenderness +++. No peritonism. No guarding. "
                "Urinalysis dipstick: nitrites+, leukocytes++, blood+."
            ),
            assessment=(
                "Acute pyelonephritis -- upper urinary tract infection. "
                "IV antibiotics required: vomiting prevents oral therapy. "
                "NICE NG112 pathway followed."
            ),
            plan=(
                "Admit to MAU for IV co-amoxiclav. MSU sent for MC&S. "
                "Blood cultures x2. IV fluids. Anti-emetics PRN. "
                "Renal ultrasound to exclude obstruction."
            ),
            plan_detail=(
                "Urine MC&S result to guide antibiotic switch if no improvement at 48h. "
                "Step-down to oral co-amoxiclav when tolerating oral intake."
            ),
            follow_up_date="2026-04-24",
            follow_up_gp="Dr. D. Ehiobu",
            follow_up_surgery="Holmhurst Medical Centre",
            created_by="Dr. D. Ehiobu",
        )

        t3a = save_test_order(nhs3, "MSU (Mid-Stream Urine) MC&S", "microbiology", "2026-04-10",
                              "Dr. D. Ehiobu", consultation_id=cid3)
        update_test_result(t3a, "2026-04-11",
                           "E. coli >10^5 CFU/mL. Sensitive to co-amoxiclav, trimethoprim, nitrofurantoin.",
                           "abnormal", "Culture confirms E. coli pyelonephritis. Sensitive to current treatment.",
                           "Continue IV co-amoxiclav. Step-down to oral when tolerating.")

        t3b = save_test_order(nhs3, "FBC (Full Blood Count)", "blood_test", "2026-04-10",
                              "Dr. D. Ehiobu", consultation_id=cid3)
        update_test_result(t3b, "2026-04-10",
                           "WBC 14.2 (neutrophilia). Hb 13.1. Plt 312.",
                           "abnormal", "Inflammatory response consistent with bacterial infection.",
                           "Repeat FBC day 2 to confirm response.")

        t3c = save_test_order(nhs3, "CRP / ESR", "blood_test", "2026-04-10",
                              "Dr. D. Ehiobu", consultation_id=cid3)
        update_test_result(t3c, "2026-04-10", "CRP 142 mg/L. ESR 56.",
                           "abnormal", "Significant inflammation. Consistent with pyelonephritis.",
                           "Repeat CRP at discharge to confirm falling trend.")

        t3d = save_test_order(nhs3, "Renal Ultrasound", "imaging", "2026-04-10",
                              "Dr. D. Ehiobu", consultation_id=cid3, notify_nhs_app=True)
        update_test_result(t3d, "2026-04-11",
                           "USS Kidneys/Bladder: No hydronephrosis. No calculi. Normal renal size.",
                           "normal", "No obstructive uropathy. Reassuring.",
                           "No further imaging required. Continue antibiotic course.")

        adm3 = save_hospital_admission(
            nhs_number=nhs3,
            admission_date="2026-04-10",
            hospital_name="East Surrey Hospital",
            ward="Medical Assessment Unit (MAU-7)",
            consultant="Dr. D. Ehiobu -- GP",
            diagnosis="Acute Pyelonephritis -- E. coli (N10)",
            treatment="IV Co-amoxiclav 1.2g TDS for 3 days, then step-down to "
                      "oral co-amoxiclav 625mg TDS for 7 days.",
            complications="None",
            expected_discharge="2026-04-13",
        )

        save_discharge_summary(
            nhs_number=nhs3,
            discharge_date="2026-04-13",
            discharge_destination="Home",
            admission_id=adm3,
            diagnosis="Acute pyelonephritis -- E. coli sensitive to co-amoxiclav. "
                      "Renal ultrasound normal. No structural abnormality.",
            treatment_given=(
                "IV Co-amoxiclav 1.2g TDS for 3 days (2026-04-10 to 2026-04-12). "
                "IV fluids 1L sodium chloride 0.9% x2. Ondansetron 4mg IV PRN."
            ),
            discharge_medications="Co-amoxiclav 625mg TDS x7 days (oral step-down).",
            follow_up_instructions=(
                "GP review in 2 weeks (2026-04-24) to confirm resolution. "
                "Complete full antibiotic course. Increase fluid intake to 2L/day. "
                "Return if fever, rigors, or worsening loin pain."
            ),
            gp_actions=(
                "1. Review MSU MC&S result -- sensitivities confirmed, current Abx appropriate. "
                "2. Consider referral to urology if recurrent UTIs (2+ in 6 months). "
                "3. Check CRP at 2-week review to confirm resolution. "
                "4. File discharge summary -- annotate antibiotic allergy status (NKDA)."
            ),
        )

        save_case_closure(
            nhs_number=nhs3,
            closed_by="Dr. D. Ehiobu",
            closure_reason="Discharge following successful treatment for acute pyelonephritis.",
            retention_date="2036-04-13",
            case_summary=(
                "34F with E. coli acute pyelonephritis. IV co-amoxiclav 3 days. "
                "Step-down to oral. Renal USS normal. Discharged day 3. "
                "GP follow-up 2026-04-24."
            ),
        )

        print("[OK] GP workflow seeded: Patient 3 (Sarah M -- Pyelonephritis)")

    # ── Patient 4: James K, 42M -- AMBER Depression -> Still Admitted ─────────
    nhs4 = "748 392 6017"
    if _gp_workflow_seeded(nhs4):
        print("[SKIP] GP workflow already seeded: Patient 4")
    else:
        cid4 = save_consultation(
            nhs_number=nhs4,
            consultation_date="2026-04-09",
            gp_name="Dr. S. Morrison",
            gp_email="s.morrison@greystonehouse.nhs.uk",
            presenting_complaint=(
                "42-year-old male with 3-week history of worsening low mood, "
                "social withdrawal, insomnia (early morning waking), poor appetite, "
                "and passive suicidal ideation (no active plan, no intent, no means)."
            ),
            examination_findings=(
                "Alert and orientated. Flat affect. Poor eye contact. "
                "PHQ-9 score: 22 (severe depression). Columbia SSRS: passive SI only. "
                "No psychotic features. No evidence of mania. "
                "Physical observations normal: T 36.9, HR 88, BP 126/82."
            ),
            assessment=(
                "Severe depressive episode without psychotic features (F32.2). "
                "Passive suicidal ideation -- MCA assessment completed, patient has capacity. "
                "Risk: moderate. Inpatient stabilisation required."
            ),
            plan=(
                "Emergency psychiatric referral to East Surrey PAU. "
                "Crisis plan co-produced with patient. Samaritans number given. "
                "Next of kin (wife) contacted with patient consent."
            ),
            plan_detail=(
                "Sertraline 50mg OD commenced. CBT referral submitted. "
                "CPN allocated -- weekly contact. Social services referral made."
            ),
            follow_up_date="2026-05-09",
            follow_up_gp="Dr. S. Morrison",
            follow_up_surgery="Greystone House Surgery",
            created_by="Dr. S. Morrison",
        )

        t4a = save_test_order(nhs4, "TFTs (Thyroid Function Tests)", "blood_test", "2026-04-09",
                              "Dr. S. Morrison", consultation_id=cid4)
        update_test_result(t4a, "2026-04-10",
                           "TSH 2.1 mIU/L (normal). T4 14.2 pmol/L (normal). No thyroid dysfunction.",
                           "normal", "Thyroid function normal -- depression not secondary to hypothyroidism.",
                           "No thyroid treatment required. Diagnosis remains primary depression.")

        t4b = save_test_order(nhs4, "FBC (Full Blood Count)", "blood_test", "2026-04-09",
                              "Dr. S. Morrison", consultation_id=cid4)
        update_test_result(t4b, "2026-04-10",
                           "Hb 13.8. WBC 7.4 (normal). Plt 224. MCV 88. Normal FBC.",
                           "normal", "No anaemia, no infection. Supports primary psychiatric diagnosis.",
                           "No further haematology investigation required.")

        # Still admitted -- no discharge summary or case closure yet
        save_hospital_admission(
            nhs_number=nhs4,
            admission_date="2026-04-09",
            hospital_name="East Surrey Hospital",
            ward="Psychiatric Assessment Unit (PAU-3)",
            consultant="Dr. S. Morrison -- GP",
            diagnosis="Severe Depressive Episode without Psychotic Features (F32.2)",
            treatment="Sertraline 50mg OD titration. Inpatient psychiatric stabilisation. "
                      "CBT referral. CPN allocated. Zopiclone 7.5mg ON short course.",
            complications="None",
            expected_discharge="2026-04-15",
        )
        # No discharge summary or case closure -- patient still admitted

        print("[OK] GP workflow seeded: Patient 4 (James K -- Depression, still admitted)")

    # ── Patient 5: Emma T, 28F -- GREEN Viral Tonsillitis -> Same-day Discharge ─
    nhs5 = "513 826 4739"
    if _gp_workflow_seeded(nhs5):
        print("[SKIP] GP workflow already seeded: Patient 5")
    else:
        cid5 = save_consultation(
            nhs_number=nhs5,
            consultation_date="2026-04-13",
            gp_name="Dr. D. Ehiobu",
            gp_email="d.ehiobu@holmhurst.nhs.uk",
            presenting_complaint=(
                "28-year-old female with 3-day history of sore throat, mild odynophagia, "
                "low-grade fever (37.6C), and fatigue. FeverPAIN score 2."
            ),
            examination_findings=(
                "T 37.6. HR 76. BP 116/74. SpO2 99%. "
                "Tonsils mildly erythematous -- no exudate, no peritonsillar bulging. "
                "No cervical lymphadenopathy. No stridor. No drooling. No trismus. "
                "FeverPAIN score: 2 (fever + purulence absent + attend within 3 days)."
            ),
            assessment=(
                "Viral tonsillitis -- low probability of streptococcal infection. "
                "FeverPAIN 2 = <40% strep probability. No antibiotics indicated (NICE NG84)."
            ),
            plan=(
                "Analgesia: ibuprofen 400mg TDS + paracetamol 1g QDS PRN. "
                "Adequate hydration. Rest 2-3 days. "
                "Safety-net advice: return if symptoms worsen, dysphagia severe, "
                "or fever persists beyond 5 days."
            ),
            plan_detail=(
                "No follow-up booked unless symptoms persist. "
                "Patient education: antibiotics not appropriate for viral sore throat."
            ),
            follow_up_date="",
            follow_up_gp="Dr. D. Ehiobu",
            follow_up_surgery="Holmhurst Medical Centre (PRN only)",
            created_by="Dr. D. Ehiobu",
        )
        # No test orders -- GREEN triage, no investigations needed

        # No hospital admission -- GP-managed same-day case closure
        save_case_closure(
            nhs_number=nhs5,
            closed_by="Dr. D. Ehiobu",
            closure_reason="Same-day GP consultation. Self-limiting viral illness. No follow-up required.",
            retention_date="2036-04-13",
            case_summary=(
                "28F with viral tonsillitis. FeverPAIN 2. Conservative management. "
                "Discharged same day. No antibiotics prescribed. Safety-net advice given."
            ),
        )

        print("[OK] GP workflow seeded: Patient 5 (Emma T -- Viral Tonsillitis)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== GP Triage POC -- Demo Data Seeding ===")
    print("Initialising database...")
    init_db()
    print("Database ready.")
    print("")

    seed_patient_1()
    seed_patient_2()
    seed_patient_3()
    seed_patient_4()
    seed_patient_5()

    print("")
    print("--- Updating pathway stage labels to new 10-stage GP pathway ---")
    update_pathway_stage_labels()

    print("")
    print("--- Seeding ward management data ---")
    seed_ward_data()

    print("")
    print("--- Seeding GP workflow data (consultations, tests, admissions, closures) ---")
    seed_gp_workflow_data()

    print("")
    print("=== Seeding complete. 5 patient journeys + GP workflow data loaded. ===")
    print("Restart the Streamlit app to see the data in the dashboard.")
