"""
src/fhir_export.py — FHIR R4 bundle generation for HandoverAI.

Generates valid FHIR R4 JSON bundles from patient data stored in the
HandoverAI database. No existing functionality is modified.

All resource constructors accept plain dicts (as returned by database.py).
"""
from __future__ import annotations

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _urgency_to_fhir_priority(urgency: str) -> str:
    """Map HandoverAI urgency strings to FHIR ServiceRequest priority codes."""
    mapping = {
        "emergency": "stat",
        "urgent":    "urgent",
        "soon":      "asap",
        "routine":   "routine",
    }
    return mapping.get((urgency or "").lower(), "routine")


def _result_flag_to_snomed(flag: str) -> str:
    """Map result_flag to SNOMED CT code for normal / abnormal finding."""
    return "263654008" if (flag or "").lower() in ("abnormal", "high", "low", "critical") else "17621005"


def _result_flag_to_status(db_status: str) -> str:
    """Map test_orders.status to FHIR DiagnosticReport status."""
    mapping = {
        "pending":   "registered",
        "resulted":  "final",
        "amended":   "amended",
    }
    return mapping.get((db_status or "").lower(), "registered")


def _nhs_subject(nhs: str) -> dict:
    """Full FHIR subject block with NHS number identifier on every resource."""
    nhs_raw = str(nhs).replace(" ", "").replace("-", "")
    return {
        "reference": f"Patient/nhs-{nhs}",
        "identifier": {
            "system": "https://fhir.nhs.uk/Id/nhs-number",
            "value":  nhs_raw,
        },
    }


def _bundle_entry(resource: dict) -> dict:
    """Wrap a FHIR resource in a Bundle entry envelope."""
    rtype = resource.get("resourceType", "")
    rid   = resource.get("id", "")
    return {
        "fullUrl":  f"urn:uuid:{rid}",
        "resource": resource,
    }


# ---------------------------------------------------------------------------
# Public resource constructors
# ---------------------------------------------------------------------------

def generate_patient_resource(patient: dict) -> dict:
    """
    Return a FHIR R4 Patient resource from a patient dict.

    The HandoverAI patients table stores: nhs_number, age, gender, description.
    There is no dedicated first_name / last_name / date_of_birth / address column,
    so these are derived from ``description`` where possible and omitted otherwise.
    """
    nhs = patient.get("nhs_number", "unknown")

    # Best-effort name extraction from description (e.g. "John Smith, 45M ...")
    description = patient.get("description", "")
    name_part   = description.split(",")[0].strip() if description else ""
    name_parts  = name_part.split() if name_part else []

    given  = [name_parts[0]] if len(name_parts) >= 1 else ["Unknown"]
    family = name_parts[-1]  if len(name_parts) >= 2 else "Unknown"

    resource: dict = {
        "resourceType": "Patient",
        "id":           f"nhs-{nhs}",
        "identifier": [{
            "system": "https://fhir.nhs.uk/Id/nhs-number",
            "value":  nhs,
        }],
        "name": [{
            "use":    "official",
            "family": family,
            "given":  given,
            "text":   name_part or nhs,
        }],
    }

    gender = (patient.get("gender") or "").lower()
    if gender:
        fhir_gender = {"male": "male", "female": "female", "m": "male", "f": "female"}.get(gender, "unknown")
        resource["gender"] = fhir_gender

    return resource


def generate_triage_condition(triage_session: dict, patient: dict) -> dict:
    """Return a FHIR R4 Condition resource for a triage session."""
    nhs        = patient.get("nhs_number", "unknown")
    session_id = triage_session.get("id", "0")
    level      = (triage_session.get("triage_decision") or "UNKNOWN").upper()
    ai_rec     = triage_session.get("recommended_action") or triage_session.get("clinical_reasoning") or ""
    recorded   = triage_session.get("created_at") or _iso_now()

    return {
        "resourceType": "Condition",
        "id":           f"triage-{session_id}",
        "clinicalStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                "code":   "active",
            }],
        },
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                "code":   "encounter-diagnosis",
            }],
        }],
        "severity": {
            "coding": [{
                "system":  "https://fhir.nhs.uk/CodeSystem/triage-severity",
                "code":    level,
                "display": level,
            }],
        },
        "subject": {
            "reference": f"Patient/nhs-{nhs}",
            "identifier": {
                "system": "https://fhir.nhs.uk/Id/nhs-number",
                "value":  nhs,
            },
        },
        "recordedDate": str(recorded),
        "note": [{"text": ai_rec}] if ai_rec else [],
    }


def generate_observation_resource(observation: dict, patient: dict) -> dict:
    """Return a FHIR R4 Observation resource (NEWS2 + vital signs)."""
    nhs    = patient.get("nhs_number", "unknown")
    obs_id = observation.get("id", "0")
    obs_dt = observation.get("obs_date") or observation.get("created_at") or _iso_now()

    def _component(code: str, display: str, value, unit: str, system: str = "http://snomed.info/sct") -> dict:
        if value is None:
            return {}
        comp: dict = {
            "code": {
                "coding": [{"system": system, "code": code, "display": display}],
            },
        }
        if isinstance(value, float):
            comp["valueQuantity"] = {"value": value, "unit": unit}
        else:
            comp["valueQuantity"] = {"value": int(value), "unit": unit}
        return comp

    components = []
    for c in [
        _component("386725007", "Body temperature",                     observation.get("temperature"),      "Cel"),
        _component("72313002",  "Systolic arterial pressure",           observation.get("bp_systolic"),      "mm[Hg]"),
        _component("364075005", "Heart rate",                           observation.get("heart_rate"),       "/min"),
        _component("59408-5",   "Oxygen saturation in Arterial blood",  observation.get("o2_sats"),          "%",
                   "http://loinc.org"),
        _component("86290005",  "Respiratory rate",                     observation.get("respiratory_rate"), "/min"),
    ]:
        if c:
            components.append(c)

    resource: dict = {
        "resourceType": "Observation",
        "id":           f"obs-{obs_id}",
        "status":       "final",
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code":   "vital-signs",
            }],
        }],
        "code": {
            "coding": [{
                "system":  "http://snomed.info/sct",
                "code":    "1104051000000101",
                "display": "Royal College of Physicians NEWS2 score",
            }],
        },
        "subject":          _nhs_subject(nhs),
        "effectiveDateTime": str(obs_dt),
    }

    news2 = observation.get("news2_score")
    if news2 is not None:
        resource["valueInteger"] = int(news2)

    if components:
        resource["component"] = components

    return resource


def generate_service_request(referral: dict, patient: dict) -> dict:
    """Return a FHIR R4 ServiceRequest resource for a referral."""
    nhs        = patient.get("nhs_number", "unknown")
    ref_id     = referral.get("id", "0")
    urgency    = referral.get("urgency", "routine")
    authored   = referral.get("created_at") or _iso_now()
    performer  = (
        referral.get("hospital_name")
        or referral.get("location")
        or referral.get("referral_name")
        or "Unknown"
    )
    reason = " — ".join(filter(None, [
        referral.get("referral_type"),
        referral.get("referral_name"),
        referral.get("specialty"),
    ])) or "Referral"

    return {
        "resourceType": "ServiceRequest",
        "id":           f"ref-{ref_id}",
        "status":       "active",
        "intent":       "referral",
        "priority":     _urgency_to_fhir_priority(urgency),
        "subject":    _nhs_subject(nhs),
        "authoredOn": str(authored),
        "requester":    {"display": "HandoverAI GP System"},
        "performer":    [{"display": performer}],
        "reasonCode":   [{"text": reason}],
    }


def generate_diagnostic_report(test_order: dict, patient: dict) -> dict:
    """Return a FHIR R4 DiagnosticReport resource for a test order / result."""
    nhs     = patient.get("nhs_number", "unknown")
    test_id = test_order.get("id", "0")
    eff_dt  = test_order.get("result_date") or test_order.get("ordered_date") or _iso_now()
    summary = test_order.get("result_summary") or test_order.get("test_name") or ""
    flag    = test_order.get("result_flag", "normal")
    status  = _result_flag_to_status(test_order.get("status", "pending"))
    snomed  = _result_flag_to_snomed(flag)
    snomed_display = "Abnormal finding" if snomed == "263654008" else "Normal finding"

    return {
        "resourceType": "DiagnosticReport",
        "id":           f"test-{test_id}",
        "status":       status,
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                "code":   "LAB",
            }],
        }],
        "subject":           _nhs_subject(nhs),
        "effectiveDateTime": str(eff_dt),
        "conclusion":       summary,
        "conclusionCode": [{
            "coding": [{
                "system":  "http://snomed.info/sct",
                "code":    snomed,
                "display": snomed_display,
            }],
        }],
    }


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------

def generate_fhir_bundle(nhs_number: str) -> dict:
    """
    Assemble a complete FHIR R4 Bundle for a patient.

    Fetches all available data from the HandoverAI database and returns a
    FHIR R4 'collection' Bundle containing:
      - Patient resource
      - Condition resources  (triage sessions)
      - Observation resources (nurse observations / NEWS2)
      - ServiceRequest resources (referrals)
      - DiagnosticReport resources (test orders)

    Returns a dict that is JSON-serialisable via json.dumps().
    Raises ValueError if the patient is not found.
    """
    from src.database import (
        get_patient,
        get_all_triage_sessions,
        get_observations,
        get_referrals,
        get_test_orders,
        get_consultations,
    )

    patient = get_patient(nhs_number)
    if not patient:
        raise ValueError(f"Patient not found: {nhs_number}")

    timestamp = _iso_now()
    entries: list[dict] = []

    # 1. Patient
    entries.append(_bundle_entry(generate_patient_resource(patient)))

    # 2. Conditions — all triage sessions for this patient
    all_sessions = get_all_triage_sessions()
    patient_sessions = [s for s in all_sessions if s.get("nhs_number") == nhs_number]
    for session in patient_sessions:
        entries.append(_bundle_entry(generate_triage_condition(session, patient)))

    # 3. Observations — nurse observations / NEWS2
    for obs in get_observations(nhs_number):
        entries.append(_bundle_entry(generate_observation_resource(obs, patient)))

    # 4. ServiceRequests — referrals
    for referral in get_referrals(nhs_number):
        entries.append(_bundle_entry(generate_service_request(referral, patient)))

    # 5. DiagnosticReports — test orders
    for test in get_test_orders(nhs_number):
        entries.append(_bundle_entry(generate_diagnostic_report(test, patient)))

    # 6. GP consultations are informational — noted in bundle meta comment only
    consultations = get_consultations(nhs_number)

    nhs_raw = nhs_number.replace(" ", "").replace("-", "")
    bundle: dict = {
        "resourceType": "Bundle",
        "id":           f"handoverai-{nhs_raw}-{timestamp.replace(':', '-').replace('.', '-')}",
        "identifier": {
            "system": "https://fhir.nhs.uk/Id/nhs-number",
            "value":  nhs_raw,
        },
        "meta": {
            "lastUpdated": timestamp,
            "profile": [
                "https://fhir.nhs.uk/STU3/StructureDefinition/GPConnect-StructuredRecord-Bundle-1",
            ],
            "tag": [{
                "system":  "https://fhir.nhs.uk/CodeSystem/handoverai-source",
                "code":    "handoverai-export",
                "display": f"HandoverAI export — {len(consultations)} GP consultation(s) on record",
            }],
        },
        "type":      "collection",
        "timestamp": timestamp,
        "total":     len(entries),
        "entry":     entries,
    }

    return bundle
