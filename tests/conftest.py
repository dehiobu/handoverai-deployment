"""
Shared pytest configuration and fixtures.

Sets a dummy OPENAI_API_KEY before any project module is imported so that
config.py does not raise ValueError during test collection.
"""
from __future__ import annotations

import json
import os
from typing import Generator
from unittest.mock import MagicMock

import pytest

# Must be set before importing config or any src module.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("MISTRAL_API_KEY", "test-mistral-key")


# ---------------------------------------------------------------------------
# Dataset / vector-store fixtures (pre-existing)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_case() -> dict:
    """A minimal valid clinical case dict."""
    return {
        "id": "test_001",
        "patient_description": "64-year-old male with crushing chest pain.",
        "chief_complaint": "Chest pain",
        "age": 64,
        "gender": "male",
        "symptoms": ["chest pain", "sweating", "nausea"],
        "duration": "40 minutes",
        "past_medical_history": ["hypertension", "type 2 diabetes"],
        "red_flags_present": ["crushing chest pain", "radiation to left arm"],
        "triage_decision": "RED",
        "urgency_timeframe": "999 immediately",
        "clinical_reasoning": "Classic ACS presentation.",
        "nice_guideline": "NG185 - Acute coronary syndromes",
        "recommended_action": "Call 999 immediately.",
        "confidence": "High",
    }


@pytest.fixture
def dataset_json_file(sample_case, tmp_path) -> str:
    """A temporary JSON dataset file in flat-list format."""
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps([sample_case]), encoding="utf-8")
    return str(path)


@pytest.fixture
def dataset_json_file_wrapped(sample_case, tmp_path) -> str:
    """A temporary JSON dataset file in {'presentations': [...]} format."""
    path = tmp_path / "dataset_wrapped.json"
    path.write_text(json.dumps({"presentations": [sample_case]}), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Database fixture — isolated SQLite per test
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_db(monkeypatch, tmp_path) -> Generator:
    """
    Provide a fresh, isolated SQLite database for each test.

    Patches the src.database module globals so every db function
    uses a temporary file that is discarded after the test.
    """
    import src.database as db_mod
    from sqlalchemy import create_engine, event as sa_event

    db_path = tmp_path / "test_gp_triage.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @sa_event.listens_for(engine, "connect")
    def _wal(conn, _rec):
        conn.execute("PRAGMA journal_mode=WAL")

    # Patch module-level globals — monkeypatch restores after test
    monkeypatch.setattr(db_mod, "_engine", engine)
    monkeypatch.setattr(db_mod, "_IS_POSTGRES", False)

    # Build schema (idempotent)
    db_mod.init_db()

    yield engine

    engine.dispose()


# ---------------------------------------------------------------------------
# Sample patient / triage / consultation fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_patient() -> dict:
    return {
        "nhs_number": "999-000-0001",
        "age": "45",
        "gender": "Female",
        "description": "45F presenting with right loin pain and fever.",
    }


@pytest.fixture
def sample_triage_session() -> dict:
    return {
        "triage_decision": "AMBER",
        "urgency_timeframe": "GP same day",
        "clinical_reasoning": "Likely pyelonephritis — fever + loin pain.",
        "red_flags": "High fever (38.9°C), rigors",
        "confidence": "High — clinical picture consistent with upper UTI",
        "nice_guideline": "NG109 - UTI in adults",
        "recommended_action": "Same-day GP review, MSU, empirical antibiotics.",
        "differentials": "Pyelonephritis, renal calculi, appendicitis",
    }


@pytest.fixture
def sample_consultation() -> dict:
    return {
        "nhs_number": "999-000-0001",
        "consultation_date": "2026-05-01",
        "gp_name": "Dr. D. Ehiobu",
        "gp_email": "dennis@nhs.uk",
        "presenting_complaint": "Right loin pain with fever for 2 days",
        "examination_findings": "Temp 38.9, BP 118/78, RR 16, tenderness at renal angle",
        "assessment": "Likely pyelonephritis",
        "plan": "Antibiotics, hydration, MSU culture",
        "plan_detail": "Nitrofurantoin 100mg MR BD 7 days, review in 48h if worsening",
        "follow_up_date": "2026-05-03",
        "follow_up_gp": "Dr. D. Ehiobu",
        "follow_up_surgery": "Holmhurst Medical Centre",
        "created_by": "dr.ehiobu",
    }


# ---------------------------------------------------------------------------
# Mock API client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_openai(mocker):
    """Mock the openai AsyncOpenAI client."""
    return mocker.patch("openai.AsyncOpenAI")


@pytest.fixture
def mock_anthropic(mocker):
    """Mock the anthropic AsyncAnthropic client."""
    return mocker.patch("anthropic.AsyncAnthropic")


@pytest.fixture
def mock_gemini(mocker):
    """Mock the google.genai.Client."""
    return mocker.patch("google.genai.Client")


@pytest.fixture
def mock_mistral(mocker):
    """Mock the mistralai Mistral client."""
    return mocker.patch("mistralai.client.Mistral")
