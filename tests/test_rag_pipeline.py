"""
Unit tests for RAG pipeline pure functions.

Covers _parse_response, _format_similar_cases, and _extract_similar_cases_data
without calling OpenAI.
"""
import pytest
from unittest.mock import MagicMock

from src.rag_pipeline import (
    _parse_response,
    _format_similar_cases,
    _extract_similar_cases_data,
    _DEFAULTS,
)


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

FULL_RESPONSE = """\
TRIAGE_DECISION: RED
URGENCY_TIMEFRAME: 999 immediately
CLINICAL_REASONING: Classic ACS presentation with crushing chest pain and left arm radiation.
RED_FLAGS: Crushing chest pain, radiation to left arm, diaphoresis
NICE_GUIDELINE: NG185 - Acute coronary syndromes
RECOMMENDED_ACTION: Call 999 immediately. Aspirin 300mg if not contraindicated.
DIFFERENTIALS: ACS, aortic dissection, pulmonary embolism
RULE_OUT: Aortic dissection first given tearing quality
FOLLOW_UP_QUESTIONS: Any previous cardiac history? Any anticoagulants? Onset sudden or gradual?
CONFIDENCE: High - classic presentation with multiple red flags
"""


class TestParseResponse:
    def test_parses_all_fields(self):
        result = _parse_response(FULL_RESPONSE)
        assert result["triage_decision"] == "RED"
        assert result["urgency_timeframe"] == "999 immediately"
        assert "ACS" in result["clinical_reasoning"]
        assert "left arm" in result["red_flags"]
        assert "NG185" in result["nice_guideline"]
        assert "Aspirin" in result["recommended_action"]
        assert "aortic dissection" in result["differentials"]
        assert "Aortic dissection" in result["rule_out"]
        assert "cardiac history" in result["follow_up_questions"]
        assert result["confidence"].startswith("High")

    def test_triage_decision_uppercased(self):
        result = _parse_response("TRIAGE_DECISION: red\nURGENCY_TIMEFRAME: now\n")
        assert result["triage_decision"] == "RED"

    def test_invalid_triage_defaults_to_amber(self):
        result = _parse_response("TRIAGE_DECISION: PURPLE\n")
        assert result["triage_decision"] == "AMBER"

    def test_partial_response_fills_defaults(self):
        result = _parse_response("TRIAGE_DECISION: GREEN\n")
        assert result["triage_decision"] == "GREEN"
        # All other fields should fall back to defaults
        assert result["clinical_reasoning"] == _DEFAULTS["clinical_reasoning"]
        assert result["red_flags"] == _DEFAULTS["red_flags"]

    def test_empty_response_returns_all_defaults(self):
        result = _parse_response("")
        assert result["triage_decision"] == "AMBER"
        for key, default_val in _DEFAULTS.items():
            assert result[key] == default_val

    def test_amber_recognised(self):
        result = _parse_response("TRIAGE_DECISION: AMBER\n")
        assert result["triage_decision"] == "AMBER"

    def test_green_recognised(self):
        result = _parse_response("TRIAGE_DECISION: GREEN\n")
        assert result["triage_decision"] == "GREEN"

    def test_fuzzy_extraction_from_sentence(self):
        # e.g. "I recommend RED triage"
        result = _parse_response("TRIAGE_DECISION: This patient needs RED triage\n")
        assert result["triage_decision"] == "RED"


# ---------------------------------------------------------------------------
# _format_similar_cases
# ---------------------------------------------------------------------------

def _make_doc(
    content: str,
    triage: str = "AMBER",
    score: float = 0.85,
    chief_complaint: str = "Headache",
) -> tuple:
    """Return a (Document, score) mock pair."""
    doc = MagicMock()
    doc.page_content = content
    doc.metadata = {
        "triage_decision": triage,
        "urgency_timeframe": "Same day GP",
        "nice_guideline": "NG123",
        "recommended_action": "Review within 24h",
        "chief_complaint": chief_complaint,
    }
    return (doc, score)


class TestFormatSimilarCases:
    def test_empty_returns_no_cases_message(self):
        result = _format_similar_cases([])
        assert result == "No similar cases found."

    def test_single_case_numbered_correctly(self):
        result = _format_similar_cases([_make_doc("Patient with headache.")])
        assert "Case 1" in result

    def test_multiple_cases_numbered_sequentially(self):
        docs = [_make_doc(f"Case content {i}") for i in range(3)]
        result = _format_similar_cases(docs)
        assert "Case 1" in result
        assert "Case 2" in result
        assert "Case 3" in result

    def test_similarity_score_included(self):
        result = _format_similar_cases([_make_doc("content")])
        assert "0.85" in result

    def test_triage_decision_included(self):
        result = _format_similar_cases([_make_doc("content", triage="RED")])
        assert "RED" in result

    def test_long_content_truncated_to_300_chars(self):
        long_content = "x" * 500
        result = _format_similar_cases([_make_doc(long_content)])
        # The formatter slices to [:300], so 500 x's should not all appear
        assert "x" * 500 not in result
        assert "x" * 300 in result


# ---------------------------------------------------------------------------
# _extract_similar_cases_data  (Phase 2 — explainability panel)
# ---------------------------------------------------------------------------

class TestExtractSimilarCasesData:
    def test_empty_returns_empty_list(self):
        assert _extract_similar_cases_data([]) == []

    def test_returns_max_three_from_larger_list(self):
        docs = [_make_doc(f"content {i}") for i in range(5)]
        result = _extract_similar_cases_data(docs)
        assert len(result) == 3

    def test_single_item_returns_one(self):
        result = _extract_similar_cases_data([_make_doc("content")])
        assert len(result) == 1

    def test_rank_starts_at_one_and_increments(self):
        docs = [_make_doc(f"c{i}") for i in range(3)]
        result = _extract_similar_cases_data(docs)
        assert [c["rank"] for c in result] == [1, 2, 3]

    def test_similarity_score_rounded_to_4dp(self):
        result = _extract_similar_cases_data([_make_doc("content", score=0.856789)])
        assert result[0]["similarity_score"] == 0.8568

    def test_similarity_pct_is_score_times_100(self):
        result = _extract_similar_cases_data([_make_doc("content", score=0.75)])
        assert result[0]["similarity_pct"] == 75.0

    def test_presentation_snippet_limited_to_250_chars(self):
        long_content = "a" * 500
        result = _extract_similar_cases_data([_make_doc(long_content)])
        assert len(result[0]["presentation_snippet"]) == 250

    def test_contains_expected_keys(self):
        result = _extract_similar_cases_data([_make_doc("content")])
        expected = {
            "rank", "similarity_score", "similarity_pct", "presentation_snippet",
            "triage_decision", "urgency_timeframe", "chief_complaint",
            "nice_guideline", "recommended_action",
        }
        assert set(result[0].keys()) == expected

    def test_metadata_fields_extracted_correctly(self):
        result = _extract_similar_cases_data(
            [_make_doc("content", triage="RED", chief_complaint="Chest pain")]
        )
        assert result[0]["triage_decision"] == "RED"
        assert result[0]["chief_complaint"] == "Chest pain"
        assert result[0]["urgency_timeframe"] == "Same day GP"

    def test_missing_metadata_fields_use_unknown(self):
        doc = MagicMock()
        doc.page_content = "some content"
        doc.metadata = {}  # no fields at all
        result = _extract_similar_cases_data([(doc, 0.5)])
        assert result[0]["triage_decision"] == "Unknown"
        assert result[0]["chief_complaint"] == "Unknown"
