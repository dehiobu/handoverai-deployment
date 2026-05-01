"""
tests/test_triage.py -- Unit and functional tests for the RAG triage pipeline.

All LLM and VectorStore calls are mocked — no real API key or ChromaDB required.
Tests validate that triage scenarios produce the correct decision level and that
the response dict contains all required fields.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared LLM response templates
# ---------------------------------------------------------------------------

def _llm_response(
    triage: str = "RED",
    urgency: str = "999 now",
    reasoning: str = "Classic ACS presentation with ST-elevation pattern.",
    red_flags: str = "Crushing chest pain, radiation to left arm, diaphoresis",
    nice: str = "NG185 - Acute coronary syndromes",
    action: str = "Call 999 immediately. Aspirin 300mg if not contraindicated.",
    differentials: str = "STEMI, NSTEMI, Aortic dissection, Pulmonary embolism",
    rule_out: str = "Aortic dissection, Pulmonary embolism",
    follow_up: str = "Any previous cardiac history? Current medications? Pain severity 1-10?",
    confidence: str = "High — presentation is classic for acute coronary syndrome.",
) -> str:
    return (
        f"TRIAGE_DECISION: {triage}\n"
        f"URGENCY_TIMEFRAME: {urgency}\n"
        f"CLINICAL_REASONING: {reasoning}\n"
        f"RED_FLAGS: {red_flags}\n"
        f"NICE_GUIDELINE: {nice}\n"
        f"RECOMMENDED_ACTION: {action}\n"
        f"DIFFERENTIALS: {differentials}\n"
        f"RULE_OUT: {rule_out}\n"
        f"FOLLOW_UP_QUESTIONS: {follow_up}\n"
        f"CONFIDENCE: {confidence}"
    )


# ---------------------------------------------------------------------------
# Pipeline fixture — mocked LLM + empty VectorStore
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_factory():
    """
    Returns a factory function that creates a RAGPipeline with a mocked LLM
    response.  Each call returns a new pipeline instance with its own mock.
    """
    def _make(llm_response_text: str):
        from src.rag_pipeline import RAGPipeline  # noqa: PLC0415

        mock_vs = MagicMock()
        mock_vs.search.return_value = []

        with patch("src.rag_pipeline.create_openai_http_clients",
                   return_value=(MagicMock(), MagicMock())):
            with patch("src.rag_pipeline.ChatOpenAI"):
                pipeline = RAGPipeline(mock_vs)

        # Replace the LLM after construction so the chain picks it up
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = MagicMock(content=llm_response_text)
        pipeline._prompt = MagicMock()
        pipeline._prompt.__or__ = MagicMock(return_value=mock_chain)

        return pipeline

    return _make


# ---------------------------------------------------------------------------
# Scenario tests — triage level validation
# ---------------------------------------------------------------------------

@pytest.mark.functional
def test_red_triage_chest_pain_scenario(pipeline_factory):
    """64M with crushing chest pain → RED (STEMI/ACS)."""
    pipeline = pipeline_factory(_llm_response("RED"))
    result = pipeline.triage_patient(
        "64M, crushing chest pain radiating to left arm for 40 minutes, sweating"
    )
    assert result["triage_decision"] == "RED"


@pytest.mark.functional
def test_red_triage_paediatric_fever_scenario(pipeline_factory):
    """6M with high fever, non-blanching rash, photophobia → RED (meningitis)."""
    pipeline = pipeline_factory(_llm_response(
        triage="RED",
        urgency="999 immediately — suspected meningococcal disease",
        reasoning="Non-blanching petechial rash with high fever in infant is meningococcal disease until proven otherwise.",
        red_flags="Non-blanching rash, high fever, photophobia, bulging fontanelle",
        nice="NG51 - Meningitis (bacterial) and meningococcal disease",
        action="Call 999 immediately. Do not delay for LP.",
    ))
    result = pipeline.triage_patient(
        "6-month-old with fever 39.8°C, non-blanching rash, photophobia, irritable"
    )
    assert result["triage_decision"] == "RED"


@pytest.mark.functional
def test_amber_triage_uti_scenario(pipeline_factory):
    """45F with dysuria, loin pain, fever → AMBER (pyelonephritis)."""
    pipeline = pipeline_factory(_llm_response(
        triage="AMBER",
        urgency="Same-day GP appointment",
        reasoning="Symptoms consistent with upper UTI/pyelonephritis.",
        red_flags="High fever 38.9°C, right loin pain",
        nice="NG109 - UTI in adults",
        action="Same-day GP review. MSU. Empirical antibiotics.",
        confidence="High — UTI with systemic features.",
    ))
    result = pipeline.triage_patient(
        "45F, dysuria 3 days, right loin pain, fever 38.9°C"
    )
    assert result["triage_decision"] == "AMBER"


@pytest.mark.functional
def test_amber_triage_mental_health_scenario(pipeline_factory):
    """Adult with severe depression, passive suicidal ideation → AMBER."""
    pipeline = pipeline_factory(_llm_response(
        triage="AMBER",
        urgency="Same-day urgent mental health assessment",
        reasoning="Passive suicidal ideation with low mood requires urgent assessment.",
        red_flags="Passive suicidal ideation, severe low mood, social isolation",
        nice="NG222 - Depression in adults",
        action="Urgent referral to CRHT or same-day GP review.",
        confidence="Medium — risk assessment required.",
    ))
    result = pipeline.triage_patient(
        "35M, severe low mood 4 weeks, not eating, passive thoughts of not wanting to be here"
    )
    assert result["triage_decision"] == "AMBER"


@pytest.mark.functional
def test_green_triage_urti_scenario(pipeline_factory):
    """28M with runny nose, mild sore throat, no fever → GREEN."""
    pipeline = pipeline_factory(_llm_response(
        triage="GREEN",
        urgency="Routine appointment or self-care",
        reasoning="Mild URTI symptoms, no systemic features, self-limiting.",
        red_flags="None identified",
        nice="NG84 - Common cold",
        action="Self-care. Paracetamol for symptom relief. Return if worsening.",
        confidence="High — mild viral URTI.",
    ))
    result = pipeline.triage_patient(
        "28M, runny nose 2 days, mild sore throat, no fever, eating and drinking normally"
    )
    assert result["triage_decision"] == "GREEN"


# ---------------------------------------------------------------------------
# Structural / contract tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_triage_returns_valid_level(pipeline_factory):
    """triage_decision must always be one of RED, AMBER, GREEN."""
    for level in ("RED", "AMBER", "GREEN"):
        pipeline = pipeline_factory(_llm_response(triage=level))
        result = pipeline.triage_patient("test patient")
        assert result["triage_decision"] in ("RED", "AMBER", "GREEN"), (
            f"Expected valid triage level, got {result['triage_decision']!r}"
        )


@pytest.mark.unit
def test_triage_returns_reasoning_text(pipeline_factory):
    """clinical_reasoning must be a non-empty string."""
    pipeline = pipeline_factory(_llm_response())
    result = pipeline.triage_patient("test patient")
    assert isinstance(result["clinical_reasoning"], str)
    assert len(result["clinical_reasoning"]) > 10


@pytest.mark.unit
def test_triage_returns_red_flags_list(pipeline_factory):
    """red_flags field must be present and non-empty."""
    pipeline = pipeline_factory(_llm_response(
        red_flags="Crushing chest pain, diaphoresis, radiation to left arm"
    ))
    result = pipeline.triage_patient("chest pain patient")
    assert "red_flags" in result
    assert isinstance(result["red_flags"], str)
    assert len(result["red_flags"]) > 0


@pytest.mark.unit
def test_triage_confidence_contains_valid_level(pipeline_factory):
    """confidence field must contain High, Medium, or Low."""
    for level in ("High", "Medium", "Low"):
        pipeline = pipeline_factory(_llm_response(
            confidence=f"{level} — evidence-based assessment."
        ))
        result = pipeline.triage_patient("test patient")
        assert level.lower() in result["confidence"].lower(), (
            f"Expected confidence level {level!r} in: {result['confidence']!r}"
        )


@pytest.mark.unit
def test_triage_returns_nice_guideline_reference(pipeline_factory):
    """nice_guideline must contain a plausible NICE reference."""
    pipeline = pipeline_factory(_llm_response(
        nice="NG185 - Acute coronary syndromes"
    ))
    result = pipeline.triage_patient("test patient")
    assert "nice_guideline" in result
    assert len(result["nice_guideline"]) > 0


@pytest.mark.unit
def test_triage_returns_differential_diagnosis(pipeline_factory):
    """differentials field must be present and non-empty."""
    pipeline = pipeline_factory(_llm_response(
        differentials="STEMI, NSTEMI, Aortic dissection, PE"
    ))
    result = pipeline.triage_patient("chest pain")
    assert "differentials" in result
    assert len(result["differentials"]) > 0


@pytest.mark.unit
def test_triage_returns_similar_cases_count(pipeline_factory):
    """similar_cases_count reflects number of retrieved cases (0 here)."""
    pipeline = pipeline_factory(_llm_response())
    result = pipeline.triage_patient("test patient")
    assert "similar_cases_count" in result
    assert result["similar_cases_count"] == 0   # mocked VectorStore returns []


@pytest.mark.functional
def test_triage_response_time_under_30_seconds(pipeline_factory):
    """Full pipeline call (with mocked LLM) must return in under 30 seconds."""
    pipeline = pipeline_factory(_llm_response())
    t0 = time.perf_counter()
    result = pipeline.triage_patient("64M chest pain")
    elapsed = time.perf_counter() - t0
    assert elapsed < 30.0, f"triage_patient took {elapsed:.2f}s — exceeds 30s limit"
    assert result["triage_decision"] in ("RED", "AMBER", "GREEN")
