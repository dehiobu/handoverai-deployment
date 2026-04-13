"""
scripts/seed_demo_data.py -- Insert 5 complete demo patient journeys.

Run from project root:
    python scripts/seed_demo_data.py

Safe to re-run -- existing records are skipped via ON CONFLICT.
All output is ASCII-only (Windows-compatible console).
"""
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import (
    init_db,
    save_patient,
    save_triage,
    save_assignment,
    save_referral,
    save_pathway_stage,
    save_audit,
    _conn,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STAGE_LABELS = {
    1: "Presentation", 2: "Triage",    3: "Assignment", 4: "Referral",
    5: "Admission",    6: "Diagnosis", 7: "Treatment",  8: "Outcome",
    9: "Aftercare",   10: "Discharge",
}


def _stage(nhs: str, num: int, data: dict, status: str = "complete",
           updated_by: str = "system") -> None:
    save_pathway_stage(nhs, num, STAGE_LABELS[num], status, data, updated_by)


def _already_seeded(nhs: str) -> bool:
    """Return True if this NHS number already has a patient row."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM patients WHERE nhs_number = ?", (nhs,)
        ).fetchone()
    return row is not None


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
    print("=== Seeding complete. 5 patient journeys loaded. ===")
    print("Restart the Streamlit app to see the data in the dashboard.")
