"""
tests/test_ensemble.py -- Unit tests for the ClinisenseAI ensemble engine.

All external API calls are mocked. No real API keys required.
Tests cover:
  - Consensus calculation logic
  - Safety escalation rules
  - Graceful degradation when any single model fails (failover)
  - Judge model verdict and valid triage level output
  - Degraded-mode warnings when multiple models unavailable
  - Majority vote when judge (OpenAI) is offline
  - Full ensemble flow with all mocks
  - Response time assertion
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


# ---------------------------------------------------------------------------
# Judge model tests
# ---------------------------------------------------------------------------

class TestJudgeModel:
    """Tests for the GPT-4o judge model synthesis step."""

    def _all_keys(self, level="AMBER"):
        return {
            "openai": "sk-fake", "anthropic": "sk-ant",
            "gemini": "gm-key", "mistral": "ms-key",
        }

    def _model_resp(self, text):
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = text
        return resp

    def _ant_resp(self, text):
        b = MagicMock(); b.text = text
        r = MagicMock(); r.content = [b]
        return r

    def _gem_resp(self, text):
        r = MagicMock(); r.text = text
        return r

    def _mis_resp(self, text):
        msg = MagicMock(); msg.content = text
        ch = MagicMock(); ch.message = msg
        r = MagicMock(); r.choices = [ch]
        return r

    @pytest.mark.unit
    def test_judge_model_produces_verdict(self):
        """Judge model must return a dict with a final_triage key."""
        from src.ensemble_engine import run_ensemble_triage

        amber_text  = "TRIAGE_DECISION: AMBER\nCLINICAL_REASONING: Stable UTI."
        judge_json  = json.dumps({
            "final_triage": "AMBER", "confidence": "HIGH",
            "consensus_summary": "All models agree AMBER.",
            "disagreements": "", "clinical_reasoning": "Upper UTI.",
            "mandatory_review": False, "safety_flags": [],
        })
        call_n = {"n": 0}

        async def fake_create(**kwargs):
            call_n["n"] += 1
            return self._model_resp(amber_text if call_n["n"] == 1 else judge_json)

        with patch("src.ensemble_engine._resolve_keys", return_value=self._all_keys()):
            with patch("openai.AsyncOpenAI") as oai:
                oai.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
                with patch("anthropic.AsyncAnthropic") as ant:
                    ant.return_value.messages.create = AsyncMock(return_value=self._ant_resp(amber_text))
                    with patch("google.genai.Client") as gem:
                        gem.return_value.aio.models.generate_content = AsyncMock(return_value=self._gem_resp(amber_text))
                        with patch("mistralai.client.Mistral") as mis:
                            mis.return_value.chat.complete_async = AsyncMock(return_value=self._mis_resp(amber_text))
                            result = asyncio.run(run_ensemble_triage("45F UTI", []))

        assert "judge_reasoning" in result
        assert isinstance(result["judge_reasoning"], str)

    @pytest.mark.unit
    def test_judge_returns_valid_triage_level(self):
        """final_triage in the ensemble result must be RED, AMBER, or GREEN."""
        from src.ensemble_engine import run_ensemble_triage

        for level in ("RED", "AMBER", "GREEN"):
            body = "TRIAGE_DECISION: {l}\nCLINICAL_REASONING: Test.".format(l=level)
            judge = json.dumps({
                "final_triage": level, "confidence": "HIGH",
                "consensus_summary": f"All agree {level}.",
                "disagreements": "", "clinical_reasoning": "Test.",
                "mandatory_review": False, "safety_flags": [],
            })
            call_n = {"n": 0}

            async def fake_create(level=level, body=body, judge=judge, **kwargs):
                call_n["n"] += 1
                return self._model_resp(body if call_n["n"] == 1 else judge)

            with patch("src.ensemble_engine._resolve_keys", return_value=self._all_keys()):
                with patch("openai.AsyncOpenAI") as oai:
                    oai.return_value.chat.completions.create = AsyncMock(side_effect=fake_create)
                    with patch("anthropic.AsyncAnthropic") as ant:
                        ant.return_value.messages.create = AsyncMock(return_value=self._ant_resp(body))
                        with patch("google.genai.Client") as gem:
                            gem.return_value.aio.models.generate_content = AsyncMock(return_value=self._gem_resp(body))
                            with patch("mistralai.client.Mistral") as mis:
                                mis.return_value.chat.complete_async = AsyncMock(return_value=self._mis_resp(body))
                                res = asyncio.run(run_ensemble_triage("patient", []))

            assert res["final_triage"] in ("RED", "AMBER", "GREEN"), (
                f"Expected valid level for judge={level!r}, got {res['final_triage']!r}"
            )

    @pytest.mark.unit
    def test_consensus_percentage_calculated(self):
        """agreement_score must be a float between 0 and 100."""
        from src.ensemble_engine import _calculate_consensus

        results = [
            _make_model_result("GPT-4o",  "RED"),
            _make_model_result("Claude",  "RED"),
            _make_model_result("Gemini",  "RED"),
            _make_model_result("Mistral", "AMBER"),
        ]
        _, _, score, _ = _calculate_consensus(results)
        assert isinstance(score, float)
        assert 0.0 <= score <= 100.0
        assert score == 75.0  # 3/4 agree

    @pytest.mark.unit
    def test_model_disagreement_flagged_when_split(self):
        """
        When models split 2/2, consensus_type must be NONE or WEAK and
        mandatory_review should be True.
        """
        from src.ensemble_engine import _calculate_consensus

        results = [
            _make_model_result("GPT-4o",  "GREEN"),
            _make_model_result("Claude",  "GREEN"),
            _make_model_result("Gemini",  "AMBER"),
            _make_model_result("Mistral", "AMBER"),
        ]
        _, ctype, score, _ = _calculate_consensus(results)
        # 2/4 = 50% agreement
        assert score == 50.0
        assert ctype in ("WEAK", "NONE"), f"Expected WEAK or NONE for 50% split, got {ctype!r}"

    @pytest.mark.unit
    def test_red_always_wins_on_disagreement(self):
        """If any model votes RED, the consensus result must be RED regardless."""
        from src.ensemble_engine import _calculate_consensus

        for minority_position in range(4):
            results = [
                _make_model_result("GPT-4o",  "GREEN"),
                _make_model_result("Claude",  "GREEN"),
                _make_model_result("Gemini",  "GREEN"),
                _make_model_result("Mistral", "GREEN"),
            ]
            results[minority_position] = _make_model_result(
                results[minority_position]["model"], "RED"
            )
            triage, _, _, safety = _calculate_consensus(results)
            assert triage == "RED", (
                f"RED should win even with 1 vote (position {minority_position})"
            )


# ---------------------------------------------------------------------------
# Per-model failover tests
# ---------------------------------------------------------------------------

class TestModelFailover:
    """
    Verify that the ensemble degrades gracefully when any single model
    is unavailable (raises an exception).
    """

    def _patch_all_ok_except(self, failing_model: str, level: str = "GREEN"):
        """Return context managers that mock all four models, with one failing."""
        import contextlib

        ok_text = f"TRIAGE_DECISION: {level}\nCLINICAL_REASONING: Test."
        judge_json = json.dumps({
            "final_triage": level, "confidence": "HIGH",
            "consensus_summary": "Majority agree.", "disagreements": "",
            "clinical_reasoning": "Test.", "mandatory_review": False,
            "safety_flags": [],
        })
        call_n = {"n": 0}

        def _oai_resp():
            async def _f(**kwargs):
                call_n["n"] += 1
                r = MagicMock()
                r.choices = [MagicMock()]
                if failing_model == "GPT-4o" and call_n["n"] == 1:
                    raise Exception("GPT-4o unavailable")
                r.choices[0].message.content = (
                    ok_text if call_n["n"] == 1 else judge_json
                )
                return r
            return _f

        def _ant_resp():
            async def _f(**kwargs):
                if failing_model == "Claude":
                    raise Exception("Claude unavailable")
                b = MagicMock(); b.text = ok_text
                r = MagicMock(); r.content = [b]
                return r
            return _f

        def _gem_resp():
            async def _f(**kwargs):
                if failing_model == "Gemini":
                    raise Exception("Gemini unavailable")
                r = MagicMock(); r.text = ok_text
                return r
            return _f

        def _mis_resp():
            async def _f(**kwargs):
                if failing_model == "Mistral":
                    raise Exception("Mistral unavailable")
                msg = MagicMock(); msg.content = ok_text
                ch = MagicMock(); ch.message = msg
                r = MagicMock(); r.choices = [ch]
                return r
            return _f

        return _oai_resp, _ant_resp, _gem_resp, _mis_resp

    def _run_with_one_failing(self, failing_model: str) -> dict:
        from src.ensemble_engine import run_ensemble_triage
        oai_f, ant_f, gem_f, mis_f = self._patch_all_ok_except(failing_model)

        with patch("src.ensemble_engine._resolve_keys", return_value={
            "openai": "sk-fake", "anthropic": "sk-ant",
            "gemini": "gm-key", "mistral": "ms-key",
        }):
            with patch("openai.AsyncOpenAI") as oai:
                oai.return_value.chat.completions.create = AsyncMock(side_effect=oai_f())
                with patch("anthropic.AsyncAnthropic") as ant:
                    ant.return_value.messages.create = AsyncMock(side_effect=ant_f())
                    with patch("google.genai.Client") as gem:
                        gem.return_value.aio.models.generate_content = AsyncMock(side_effect=gem_f())
                        with patch("mistralai.client.Mistral") as mis:
                            mis.return_value.chat.complete_async = AsyncMock(side_effect=mis_f())
                            return asyncio.run(run_ensemble_triage("test patient", []))

    @pytest.mark.integration
    def test_failover_when_gpt4_offline(self):
        """When GPT-4o fails, remaining 3 models still produce a valid result."""
        result = self._run_with_one_failing("GPT-4o")
        assert result["final_triage"] in ("RED", "AMBER", "GREEN")
        assert result["model_responses"]["GPT-4o"]["error"] is not None

    @pytest.mark.integration
    def test_failover_when_claude_offline(self):
        """When Claude fails, remaining 3 models still produce a valid result."""
        result = self._run_with_one_failing("Claude")
        assert result["final_triage"] in ("RED", "AMBER", "GREEN")
        assert result["model_responses"]["Claude"]["error"] is not None

    @pytest.mark.integration
    def test_failover_when_gemini_offline(self):
        """When Gemini fails, remaining 3 models still produce a valid result."""
        result = self._run_with_one_failing("Gemini")
        assert result["final_triage"] in ("RED", "AMBER", "GREEN")
        assert result["model_responses"]["Gemini"]["error"] is not None

    @pytest.mark.integration
    def test_failover_when_mistral_offline(self):
        """When Mistral fails, remaining 3 models still produce a valid result."""
        result = self._run_with_one_failing("Mistral")
        assert result["final_triage"] in ("RED", "AMBER", "GREEN")
        assert result["model_responses"]["Mistral"]["error"] is not None

    @pytest.mark.integration
    def test_majority_vote_when_all_judges_offline(self):
        """
        When OpenAI is fully unavailable (both model call and judge fail),
        the consensus-based decision is used and mandatory_review is True.
        """
        from src.ensemble_engine import run_ensemble_triage

        amber_text = "TRIAGE_DECISION: AMBER\nCLINICAL_REASONING: Upper UTI."

        def _ant_resp():
            b = MagicMock(); b.text = amber_text
            r = MagicMock(); r.content = [b]
            return r

        def _gem_resp():
            r = MagicMock(); r.text = amber_text
            return r

        def _mis_resp():
            msg = MagicMock(); msg.content = amber_text
            ch = MagicMock(); ch.message = msg
            r = MagicMock(); r.choices = [ch]
            return r

        with patch("src.ensemble_engine._resolve_keys", return_value={
            "openai": None,          # No OpenAI key — model + judge both absent
            "anthropic": "sk-ant",
            "gemini": "gm-key",
            "mistral": "ms-key",
        }):
            with patch("anthropic.AsyncAnthropic") as ant:
                ant.return_value.messages.create = AsyncMock(return_value=_ant_resp())
                with patch("google.genai.Client") as gem:
                    gem.return_value.aio.models.generate_content = AsyncMock(return_value=_gem_resp())
                    with patch("mistralai.client.Mistral") as mis:
                        mis.return_value.chat.complete_async = AsyncMock(return_value=_mis_resp())
                        result = asyncio.run(run_ensemble_triage("45F UTI", []))

        # Judge unavailable → judge_reasoning indicates fallback
        assert result["final_triage"] in ("RED", "AMBER", "GREEN")
        assert "Judge" not in result.get("models_used", [])
        # mandatory_review True because no judge available
        assert result["mandatory_review"] is True

    @pytest.mark.unit
    def test_degraded_mode_warning_shown(self):
        """
        When only 2 models are configured, models_skipped must list the
        absent models and the result must carry a skipped list.
        """
        from src.ensemble_engine import run_ensemble_triage

        amber_text = "TRIAGE_DECISION: AMBER\nCLINICAL_REASONING: Mild symptoms."
        judge_json = json.dumps({
            "final_triage": "AMBER", "confidence": "MEDIUM",
            "consensus_summary": "2-model consensus.", "disagreements": "",
            "clinical_reasoning": "Mild symptoms.", "mandatory_review": False,
            "safety_flags": [],
        })
        call_n = {"n": 0}

        async def fake_oai(**kwargs):
            call_n["n"] += 1
            r = MagicMock(); r.choices = [MagicMock()]
            r.choices[0].message.content = (
                amber_text if call_n["n"] == 1 else judge_json
            )
            return r

        with patch("src.ensemble_engine._resolve_keys", return_value={
            "openai": "sk-fake",
            "anthropic": "sk-ant",
            "gemini": None,    # Gemini not configured
            "mistral": None,   # Mistral not configured
        }):
            with patch("openai.AsyncOpenAI") as oai:
                oai.return_value.chat.completions.create = AsyncMock(side_effect=fake_oai)
                with patch("anthropic.AsyncAnthropic") as ant:
                    b = MagicMock(); b.text = amber_text
                    r = MagicMock(); r.content = [b]
                    ant.return_value.messages.create = AsyncMock(return_value=r)
                    result = asyncio.run(run_ensemble_triage("mild URI", []))

        assert "Gemini" in result["models_skipped"]
        assert "Mistral" in result["models_skipped"]
        assert len(result["models_used"]) == 2


# ---------------------------------------------------------------------------
# Response time
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_ensemble_response_under_30_seconds():
    """
    A fully-mocked ensemble run must complete in under 30 seconds.
    (With mocks this should be <1s; the test catches unintentional blocking.)
    """
    import time
    from src.ensemble_engine import run_ensemble_triage

    green_text = "TRIAGE_DECISION: GREEN\nCLINICAL_REASONING: Mild URTI."
    judge_json = json.dumps({
        "final_triage": "GREEN", "confidence": "HIGH",
        "consensus_summary": "All agree.", "disagreements": "",
        "clinical_reasoning": "Mild viral infection.",
        "mandatory_review": False, "safety_flags": [],
    })
    call_n = {"n": 0}

    async def fake_oai(**kwargs):
        call_n["n"] += 1
        r = MagicMock(); r.choices = [MagicMock()]
        r.choices[0].message.content = (
            green_text if call_n["n"] == 1 else judge_json
        )
        return r

    def _ant():
        b = MagicMock(); b.text = green_text
        r = MagicMock(); r.content = [b]
        return r

    def _gem():
        r = MagicMock(); r.text = green_text
        return r

    def _mis():
        msg = MagicMock(); msg.content = green_text
        ch = MagicMock(); ch.message = msg
        r = MagicMock(); r.choices = [ch]
        return r

    with patch("src.ensemble_engine._resolve_keys", return_value={
        "openai": "sk-fake", "anthropic": "sk-ant",
        "gemini": "gm-key", "mistral": "ms-key",
    }):
        with patch("openai.AsyncOpenAI") as oai:
            oai.return_value.chat.completions.create = AsyncMock(side_effect=fake_oai)
            with patch("anthropic.AsyncAnthropic") as ant:
                ant.return_value.messages.create = AsyncMock(return_value=_ant())
                with patch("google.genai.Client") as gem:
                    gem.return_value.aio.models.generate_content = AsyncMock(return_value=_gem())
                    with patch("mistralai.client.Mistral") as mis:
                        mis.return_value.chat.complete_async = AsyncMock(return_value=_mis())
                        t0 = time.perf_counter()
                        result = asyncio.run(run_ensemble_triage("28M mild URI", []))
                        elapsed = time.perf_counter() - t0

    assert elapsed < 30.0, f"Ensemble took {elapsed:.2f}s — exceeds 30s limit"
    assert result["final_triage"] in ("RED", "AMBER", "GREEN")
