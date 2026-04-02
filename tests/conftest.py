"""
Shared pytest configuration.

Sets a dummy OPENAI_API_KEY before any project module is imported so that
config.py does not raise ValueError during test collection.
"""
import os
import json
import tempfile

import pytest

# Must be set before importing config or any src module.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key")


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
