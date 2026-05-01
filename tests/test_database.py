"""
tests/test_database.py -- Integration tests for src/database.py.

All tests run against an isolated in-memory-like SQLite file (via the
`isolated_db` fixture in conftest.py).  No Supabase / PostgreSQL required.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Connection / schema
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_db_connection(isolated_db):
    """The engine should be alive and accept a simple query."""
    from sqlalchemy import text
    with isolated_db.connect() as conn:
        result = conn.execute(text("SELECT 1")).fetchone()
    assert result[0] == 1


@pytest.mark.integration
def test_init_db_creates_all_tables(isolated_db):
    """init_db() must create every expected table."""
    expected_tables = {
        "patients",
        "triage_sessions",
        "assignments",
        "referrals",
        "pathway_stages",
        "letters",
        "audit_log",
        "ward_logs",
        "nurse_observations",
        "medications",
        "safeguarding_flags",
        "discharge_checklist",
        "gp_consultations",
        "test_orders",
        "login_audit",
    }
    from sqlalchemy import text
    with isolated_db.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
    found = {r[0] for r in rows}
    missing = expected_tables - found
    assert not missing, f"Tables missing after init_db(): {missing}"


# ---------------------------------------------------------------------------
# Patient CRUD
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_save_and_retrieve_patient(isolated_db, sample_patient):
    """save_patient() then get_patient() returns the same record."""
    from src.database import save_patient, get_patient

    save_patient(**sample_patient)
    record = get_patient(sample_patient["nhs_number"])

    assert record is not None
    assert record["nhs_number"] == sample_patient["nhs_number"]
    assert record["age"] == sample_patient["age"]
    assert record["gender"] == sample_patient["gender"]


@pytest.mark.integration
def test_get_patient_by_nhs_number(isolated_db, sample_patient):
    """get_patient() returns None for an unknown NHS number."""
    from src.database import get_patient

    assert get_patient("000-000-XXXX") is None


@pytest.mark.integration
def test_nhs_number_unique_constraint(isolated_db, sample_patient):
    """
    Saving two patients with the same NHS number upserts (ON CONFLICT DO UPDATE).
    The database must contain exactly one row with the latest values.
    """
    from src.database import save_patient, get_patient
    from sqlalchemy import text

    save_patient(**sample_patient)
    # Save again with updated age — should upsert, not error
    save_patient(
        nhs_number=sample_patient["nhs_number"],
        age="46",
        gender=sample_patient["gender"],
        description="Updated description",
    )

    # Only one row
    with isolated_db.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM patients WHERE nhs_number=:nhs"),
            {"nhs": sample_patient["nhs_number"]},
        ).fetchone()[0]
    assert count == 1

    # Values reflect the second save
    record = get_patient(sample_patient["nhs_number"])
    assert record["age"] == "46"


# ---------------------------------------------------------------------------
# Triage session
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_save_triage_session(isolated_db, sample_patient, sample_triage_session):
    """save_triage() inserts a row and returns a positive integer id."""
    from src.database import save_patient, save_triage

    save_patient(**sample_patient)
    row_id = save_triage(
        nhs_number=sample_patient["nhs_number"],
        result_dict=sample_triage_session,
        response_time=2.5,
    )
    assert isinstance(row_id, int)
    assert row_id > 0


@pytest.mark.integration
def test_save_triage_with_ensemble_results(isolated_db, sample_patient, sample_triage_session):
    """save_triage() correctly stores ensemble_results as JSON."""
    from src.database import save_patient, save_triage
    from sqlalchemy import text

    save_patient(**sample_patient)
    ensemble = {
        "final_triage": "AMBER",
        "confidence": "HIGH",
        "agreement_score": 75.0,
        "consensus_type": "STRONG",
    }
    row_id = save_triage(
        nhs_number=sample_patient["nhs_number"],
        result_dict=sample_triage_session,
        response_time=4.2,
        ensemble_results=ensemble,
    )

    with isolated_db.connect() as conn:
        row = conn.execute(
            text("SELECT ensemble_results FROM triage_sessions WHERE id=:id"),
            {"id": row_id},
        ).fetchone()

    import json
    stored = json.loads(row[0])
    assert stored["final_triage"] == "AMBER"
    assert stored["agreement_score"] == 75.0


# ---------------------------------------------------------------------------
# GP Consultations
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_save_gp_consultation(isolated_db, sample_patient, sample_consultation):
    """save_consultation() returns a positive integer id."""
    from src.database import save_patient, save_consultation

    save_patient(**sample_patient)
    row_id = save_consultation(**sample_consultation)
    assert isinstance(row_id, int)
    assert row_id > 0


@pytest.mark.integration
def test_multiple_consultations_same_patient(isolated_db, sample_patient, sample_consultation):
    """Multiple consultations for the same patient are all stored."""
    from src.database import save_patient, save_consultation, get_consultations

    save_patient(**sample_patient)
    nhs = sample_patient["nhs_number"]

    save_consultation(**sample_consultation)
    save_consultation(
        nhs_number=nhs,
        consultation_date="2026-05-03",
        gp_name="Dr. D. Ehiobu",
        presenting_complaint="Follow-up — improving",
    )

    records = get_consultations(nhs)
    assert len(records) == 2


@pytest.mark.integration
def test_consultation_history_ordered_by_date(isolated_db, sample_patient):
    """get_consultations() returns records newest-first."""
    from src.database import save_patient, save_consultation, get_consultations

    save_patient(**sample_patient)
    nhs = sample_patient["nhs_number"]

    save_consultation(
        nhs_number=nhs,
        consultation_date="2026-04-01",
        gp_name="Dr. A",
        presenting_complaint="First visit",
    )
    save_consultation(
        nhs_number=nhs,
        consultation_date="2026-05-01",
        gp_name="Dr. B",
        presenting_complaint="Follow-up",
    )

    records = get_consultations(nhs)
    assert records[0]["consultation_date"] >= records[1]["consultation_date"], (
        "Consultations should be returned newest-first"
    )


# ---------------------------------------------------------------------------
# Test orders and results
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_save_test_order(isolated_db, sample_patient):
    """save_test_order() returns a positive integer id."""
    from src.database import save_patient, save_test_order

    save_patient(**sample_patient)
    order_id = save_test_order(
        nhs_number=sample_patient["nhs_number"],
        test_name="FBC (Full Blood Count)",
        test_type="blood",
        ordered_date="2026-05-01",
        ordered_by="Dr. D. Ehiobu",
    )
    assert isinstance(order_id, int)
    assert order_id > 0


@pytest.mark.integration
def test_save_test_result_against_order(isolated_db, sample_patient):
    """update_test_result() marks a test order as resulted and stores the result."""
    from src.database import save_patient, save_test_order, update_test_result
    from sqlalchemy import text

    save_patient(**sample_patient)
    order_id = save_test_order(
        nhs_number=sample_patient["nhs_number"],
        test_name="CRP / ESR",
        test_type="blood",
        ordered_date="2026-05-01",
        ordered_by="Dr. D. Ehiobu",
    )

    update_test_result(
        test_id=order_id,
        result_date="2026-05-02",
        result_summary="CRP 145 (H) — elevated, consistent with bacterial infection",
        result_flag="high",
        gp_review_notes="Consistent with pyelonephritis — continue antibiotics",
        action_after_result="Review in 48h",
    )

    with isolated_db.connect() as conn:
        row = conn.execute(
            text("SELECT status, result_flag FROM test_orders WHERE id=:id"),
            {"id": order_id},
        ).fetchone()

    assert row[0] == "resulted"
    assert row[1] == "high"


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_save_referral_letter_type(isolated_db, sample_patient):
    """save_referral_full() stores a letter-type referral."""
    from src.database import save_patient, save_referral_full, get_referrals

    save_patient(**sample_patient)
    save_referral_full(
        nhs_number=sample_patient["nhs_number"],
        referral_category="secondary_care",
        referral_type="letter",
        referral_name="Urology — Renal calculi query",
        urgency="Routine",
        hospital_name="East Surrey Hospital",
        department="Urology",
    )

    records = get_referrals(sample_patient["nhs_number"])
    assert len(records) == 1
    assert records[0]["referral_type"] == "letter"
    assert records[0]["department"] == "Urology"


@pytest.mark.integration
def test_save_referral_email_type(isolated_db, sample_patient):
    """save_referral_full() stores an email-type referral."""
    from src.database import save_patient, save_referral_full, get_referrals

    save_patient(**sample_patient)
    save_referral_full(
        nhs_number=sample_patient["nhs_number"],
        referral_category="secondary_care",
        referral_type="email",
        referral_name="Cardiology — ECG review",
        urgency="Urgent",
        hospital_name="East Surrey Hospital",
        department="Cardiology",
        email_sent=True,
    )

    records = get_referrals(sample_patient["nhs_number"])
    assert len(records) == 1
    assert records[0]["referral_type"] == "email"
    assert records[0]["email_sent"] == 1


@pytest.mark.integration
def test_save_referral_ereferral_type(isolated_db, sample_patient):
    """save_referral_full() stores an e-referral with a reference number."""
    from src.database import save_patient, save_referral_full, get_referrals

    save_patient(**sample_patient)
    save_referral_full(
        nhs_number=sample_patient["nhs_number"],
        referral_category="secondary_care",
        referral_type="ereferral",
        referral_name="Nephrology — CKD follow-up",
        urgency="Routine",
        hospital_name="East Surrey Hospital",
        department="Nephrology",
        ereferral_reference="REF-2026-000123",
        ereferral_status="submitted",
    )

    records = get_referrals(sample_patient["nhs_number"])
    assert len(records) == 1
    assert records[0]["referral_type"] == "ereferral"
    assert records[0]["ereferral_reference"] == "REF-2026-000123"
    assert records[0]["ereferral_status"] == "submitted"
