"""
tests/test_ensemble.py -- Unit tests for the ClinisenseAI ensemble engine.

All external API calls are mocked. No real API keys required.
Tests cover:
  - Consensus calculation logic
  - Safety escalation rules
  - Graceful degradation when a model fails
  - Judge model prompt construction
  - Full ensemble flow with all mocks
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_model_result(model: str, level: str, error=None):
    return {
        "model": model,
        "response": f"TRIAGE_DECISION: {level}\nCLINICAL_REASONING: Test reasoning.",
        "triage_level": level if not error else None,
        "response_time": 1.0,
        "error": error,
    }


# ---------------------------------------------------------------------------
# _extract_triage_level
# ---------------------------------------------------------------------------

class TestExtractTriageLevel:
    def test_labelled_field(self):
        from src.ensemble_engine import _extract_triage_level
        text = "Some preamble\nTRIAGE_DECISION: RED\nmore text"
        assert _extract_triage_level(text) == "RED"

    def test_bare_word(self):
        from src.ensemble_engine import _extract_triage_level
        text = "This patient should be classified as AMBER urgency."
        assert _extract_triage_level(text) == "AMBER"

    def test_no_level_defaults_amber(self):
        from src.ensemble_engine import _extract_triage_level
        text = "Unable to determine triage."
        assert _extract_triage_level(text) == "AMBER"

    def test_green_detected(self):
        from src.ensemble_engine import _extract_triage_level
        text = "TRIAGE_DECISION: GREEN"
        assert _extract_triage_level(text) == "GREEN"

    def test_labelled_field_takes_priority_over_bare_word(self):
        from src.ensemble_engine import _extract_triage_level
        # If labelled AMBER but word RED appears in reasoning — trust the label
        text = "TRIAGE_DECISION: AMBER\nCLINICAL_REASONING: Rule out RED flags."
        assert _extract_triage_level(text) == "AMBER"


# ---------------------------------------------------------------------------
# _calculate_consensus
# ---------------------------------------------------------------------------

class TestCalculateConsensus:
    def test_strong_consensus_three_agree(self):
        from src.ensemble_engine import _calculate_consensus
        results = [
            _make_model_result("GPT-4o",  "RED"),
            _make_model_result("Claude",  "RED"),
            _make_model_result("Gemini",  "RED"),
            _make_model_result("Mistral", "AMBER"),
        ]
        triage, ctype, score, safety = _calculate_consensus(results)
        assert triage == "RED"
        assert ctype  == "STRONG"
        assert score  == 75.0

    def test_strong_consensus_all_four_agree(self):
        from src.ensemble_engine import _calculate_consensus
        results = [_make_model_result(m, "GREEN") for m in ["GPT-4o","Claude","Gemini","Mistral"]]
        triage, ctype, score, _ = _calculate_consensus(results)
        assert triage == "GREEN"
        assert ctype  == "STRONG"
        assert score  == 100.0

    def test_weak_consensus_two_of_three(self):
        from src.ensemble_engine import _calculate_consensus
        results = [
            _make_model_result("GPT-4o", "AMBER"),
            _make_model_result("Claude", "AMBER"),
            _make_model_result("Gemini", "RED"),
        ]
        triage, ctype, score, _ = _calculate_consensus(results)
        # Safety escalation: RED present → escalated
        assert triage == "RED"

    def test_no_consensus_all_differ(self):
        from src.ensemble_engine import _calculate_consensus
        results = [
            _make_model_result("GPT-4o",  "RED"),
            _make_model_result("Claude",  "AMBER"),
            _make_model_result("Gemini",  "GREEN"),
            _make_model_result("Mistral", "AMBER"),
        ]
        triage, ctype, score, safety = _calculate_consensus(results)
        # RED escalation wins
        assert triage == "RED"

    def test_safety_escalation_red_wins(self):
        from src.ensemble_engine import _calculate_consensus
        results = [
            _make_model_result("GPT-4o",  "AMBER"),
            _make_model_result("Claude",  "AMBER"),
            _make_model_result("Gemini",  "RED"),
            _make_model_result("Mistral", "AMBER"),
        ]
        triage, ctype, score, safety = _calculate_consensus(results)
        assert triage == "RED"
        assert "RED" in safety or "escalated" in safety.lower()

    def test_error_model_excluded_from_consensus(self):
        from src.ensemble_engine import _calculate_consensus
        results = [
            _make_model_result("GPT-4o",  "GREEN"),
            _make_model_result("Claude",  "GREEN"),
            _make_model_result("Gemini",  None, error="Timeout"),
            _make_model_result("Mistral", "GREEN"),
        ]
        triage, ctype, score, _ = _calculate_consensus(results)
        assert triage == "GREEN"
        assert score  == 100.0

    def test_all_models_fail_defaults_amber(self):
        from src.ensemble_engine import _calculate_consensus
        results = [
            _make_model_result("GPT-4o",  None, error="API error"),
            _make_model_result("Claude",  None, error="Timeout"),
        ]
        triage, ctype, score, safety = _calculate_consensus(results)
        assert triage == "AMBER"
        assert ctype  == "NONE"


# ---------------------------------------------------------------------------
# run_ensemble_triage — insufficient keys guard
# ---------------------------------------------------------------------------

class TestEnsembleInsufficientKeys:
    def test_returns_fallback_if_fewer_than_two_keys(self):
        from src.ensemble_engine import run_ensemble_triage

        with patch("src.ensemble_engine._resolve_keys", return_value={
            "openai": "sk-fake", "anthropic": None, "gemini": None, "mistral": None,
        }):
            result = asyncio.run(run_ensemble_triage("test", []))

        assert result["final_triage"] == "AMBER"
        assert result["mandatory_review"] is True
        assert "Insufficient models" in result["safety_flags"][0]


# ---------------------------------------------------------------------------
# run_ensemble_triage — full mock flow
# ---------------------------------------------------------------------------

class TestFullEnsembleFlow:
    def _make_openai_response(self, content: str):
        msg = MagicMock()
        msg.content = content
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    def _make_anthropic_response(self, text: str):
        block = MagicMock()
        block.text = text
        resp = MagicMock()
        resp.content = [block]
        return resp

    def _make_gemini_response(self, text: str):
        resp = MagicMock()
        resp.text = text
        return resp

    def _make_mistral_response(self, text: str):
        msg = MagicMock()
        msg.content = text
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    def test_all_models_agree_red(self):
        """All four models return RED → strong consensus, no mandatory review."""
        from src.ensemble_engine import run_ensemble_triage

        red_text = "TRIAGE_DECISION: RED\nCLINICAL_REASONING: Acute MI suspected."
        judge_json = json.dumps({
            "final_triage": "RED",
            "confidence": "HIGH",
            "consensus_summary": "All models agree RED.",
            "disagreements": "",
            "clinical_reasoning": "Synthesised: acute MI.",
            "mandatory_review": False,
            "safety_flags": [],
        })

        openai_resp       = self._make_openai_response(red_text)
        openai_judge_resp = self._make_openai_response(judge_json)
        anthropic_resp    = self._make_anthropic_response(red_text)
        gemini_resp       = self._make_gemini_response(red_text)
        mistral_resp      = self._make_mistral_response(red_text)

        call_count = {"n": 0}
        async def fake_openai_create(**kwargs):
            call_count["n"] += 1
            # First call = model; second call = judge
            if call_count["n"] == 1:
                return openai_resp
            return openai_judge_resp

        with patch("src.ensemble_engine._resolve_keys", return_value={
            "openai": "sk-fake", "anthropic": "sk-ant", "gemini": "gm-key", "mistral": "ms-key",
        }):
            with patch("openai.AsyncOpenAI") as mock_oai:
                mock_oai.return_value.chat.completions.create = AsyncMock(
                    side_effect=fake_openai_create
                )
                with patch("anthropic.AsyncAnthropic") as mock_ant:
                    mock_ant.return_value.messages.create = AsyncMock(
                        return_value=anthropic_resp
                    )
                    with patch("google.genai.Client") as mock_gem:
                        mock_gem.return_value.aio.models.generate_content = AsyncMock(
                            return_value=gemini_resp
                        )
                        with patch("mistralai.client.Mistral") as mock_mis:
                            mock_mis.return_value.chat.complete_async = AsyncMock(
                                return_value=mistral_resp
                            )
                            result = asyncio.run(
                                run_ensemble_triage("64M chest pain", [])
                            )

        assert result["final_triage"] == "RED"
        assert result["consensus_type"] in ("STRONG", "WEAK")
        assert result["agreement_score"] > 0
        assert "GPT-4o" in result["model_responses"]
        assert "Claude"  in result["model_responses"]
        assert "Gemini"  in result["model_responses"]
        assert "Mistral" in result["model_responses"]

    def test_one_model_fails_gracefully(self):
        """Gemini fails → 3-model ensemble still completes."""
        from src.ensemble_engine import run_ensemble_triage

        green_text = "TRIAGE_DECISION: GREEN\nCLINICAL_REASONING: Mild URI."
        judge_json = json.dumps({
            "final_triage": "GREEN",
            "confidence": "HIGH",
            "consensus_summary": "Majority GREEN.",
            "disagreements": "",
            "clinical_reasoning": "Routine.",
            "mandatory_review": False,
            "safety_flags": [],
        })

        openai_resp       = self._make_openai_response(green_text)
        openai_judge_resp = self._make_openai_response(judge_json)
        anthropic_resp    = self._make_anthropic_response(green_text)
        mistral_resp      = self._make_mistral_response(green_text)

        call_count = {"n": 0}
        async def fake_openai_create(**kwargs):
            call_count["n"] += 1
            return openai_resp if call_count["n"] == 1 else openai_judge_resp

        with patch("src.ensemble_engine._resolve_keys", return_value={
            "openai": "sk-fake", "anthropic": "sk-ant", "gemini": "gm-key", "mistral": "ms-key",
        }):
            with patch("openai.AsyncOpenAI") as mock_oai:
                mock_oai.return_value.chat.completions.create = AsyncMock(
                    side_effect=fake_openai_create
                )
                with patch("anthropic.AsyncAnthropic") as mock_ant:
                    mock_ant.return_value.messages.create = AsyncMock(
                        return_value=anthropic_resp
                    )
                    with patch("google.genai.Client") as mock_gem:
                        # Gemini raises an exception
                        mock_gem.return_value.aio.models.generate_content = AsyncMock(
                            side_effect=Exception("Gemini API error")
                        )
                        with patch("mistralai.client.Mistral") as mock_mis:
                            mock_mis.return_value.chat.complete_async = AsyncMock(
                                return_value=mistral_resp
                            )
                            result = asyncio.run(
                                run_ensemble_triage("28M mild URI", [])
                            )

        # Gemini failed but result is still returned
        assert result["final_triage"] in ("RED", "AMBER", "GREEN")
        assert "Gemini" in result["model_responses"]
        assert result["model_responses"]["Gemini"]["error"] is not None

    def test_safety_escalation_in_full_flow(self):
        """Judge returns AMBER but one model said RED → escalated to RED."""
        from src.ensemble_engine import run_ensemble_triage

        red_text   = "TRIAGE_DECISION: RED\nCLINICAL_REASONING: Possible MI."
        amber_text = "TRIAGE_DECISION: AMBER\nCLINICAL_REASONING: Chest pain query."
        # Judge returns AMBER — should be overridden to RED
        judge_json = json.dumps({
            "final_triage": "AMBER",
            "confidence": "MEDIUM",
            "consensus_summary": "Mixed.",
            "disagreements": "GPT-4o said RED.",
            "clinical_reasoning": "Query chest pain.",
            "mandatory_review": False,
            "safety_flags": [],
        })

        call_count = {"n": 0}
        async def fake_openai_create(**kwargs):
            call_count["n"] += 1
            resp = MagicMock()
            resp.choices = [MagicMock()]
            # First call returns RED text (GPT-4o model call)
            resp.choices[0].message.content = (
                red_text if call_count["n"] == 1 else judge_json
            )
            return resp

        def _make_ant_resp(text):
            block = MagicMock(); block.text = text
            r = MagicMock(); r.content = [block]
            return r

        def _make_gem_resp(text):
            r = MagicMock(); r.text = text
            return r

        def _make_mis_resp(text):
            msg = MagicMock(); msg.content = text
            ch = MagicMock(); ch.message = msg
            r = MagicMock(); r.choices = [ch]
            return r

        with patch("src.ensemble_engine._resolve_keys", return_value={
            "openai": "sk-fake", "anthropic": "sk-ant", "gemini": "gm-key", "mistral": "ms-key",
        }):
            with patch("openai.AsyncOpenAI") as mock_oai:
                mock_oai.return_value.chat.completions.create = AsyncMock(
                    side_effect=fake_openai_create
                )
                with patch("anthropic.AsyncAnthropic") as mock_ant:
                    mock_ant.return_value.messages.create = AsyncMock(
                        return_value=_make_ant_resp(amber_text)
                    )
                    with patch("google.genai.Client") as mock_gem:
                        mock_gem.return_value.aio.models.generate_content = AsyncMock(
                            return_value=_make_gem_resp(amber_text)
                        )
                        with patch("mistralai.client.Mistral") as mock_mis:
                            mock_mis.return_value.chat.complete_async = AsyncMock(
                                return_value=_make_mis_resp(amber_text)
                            )
                            result = asyncio.run(
                                run_ensemble_triage("Chest pain", [])
                            )

        # Safety escalation: GPT-4o said RED → must be RED regardless of judge
        assert result["final_triage"] == "RED"
        assert any("escalation" in f.lower() or "RED" in f for f in result["safety_flags"])
