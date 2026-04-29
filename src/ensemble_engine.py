"""
src/ensemble_engine.py -- ClinisenseAI Multi-Model Consensus Triage Engine.

Sends the same triage prompt simultaneously to GPT-4o, Claude, Gemini, and
Mistral via asyncio.gather(), then uses GPT-4o as a judge model to synthesise
a final clinical recommendation.

Public API:
    result = asyncio.run(run_ensemble_triage(patient_presentation, similar_cases))

Result dict keys — see RETURN VALUE section in module docstring.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any

# ---------------------------------------------------------------------------
# Prompt templates (mirrors src/rag_pipeline.py)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert NHS GP triage assistant. Your role is to analyse patient \
presentations and provide safe, evidence-based triage decisions aligned with \
NHS and NICE guidelines.

Always err on the side of caution: when in doubt, escalate.

Triage levels:
  RED   - Emergency. Potentially life-threatening. Immediate 999 or ED.
  AMBER - Urgent. Needs same-day GP or urgent care assessment.
  GREEN - Routine. Can be managed with a standard GP appointment or self-care.\
"""

_HUMAN_TEMPLATE = """\
SIMILAR VALIDATED CASES (use these as clinical reference):
{similar_cases}

---

PATIENT PRESENTATION:
{patient_description}

---

Provide your triage assessment in EXACTLY the following format. \
Use the exact labels shown; each value runs until the next label.

TRIAGE_DECISION: [RED/AMBER/GREEN]
URGENCY_TIMEFRAME: [specific timeframe, e.g. "999 now", "GP same day", "Routine appointment within 2 weeks"]
CLINICAL_REASONING: [detailed clinical reasoning explaining your decision]
RED_FLAGS: [list any red-flag symptoms present, or "None identified"]
NICE_GUIDELINE: [most relevant NICE guideline reference, e.g. "NG185 - Acute coronary syndromes"]
RECOMMENDED_ACTION: [specific action the triage clinician should take]
DIFFERENTIALS: [2-4 differential diagnoses to consider]
RULE_OUT: [most dangerous conditions that must be excluded first]
FOLLOW_UP_QUESTIONS: [2-3 targeted questions to ask the patient]
CONFIDENCE: [High/Medium/Low - brief explanation of your confidence level]\
"""

_JUDGE_TEMPLATE = """\
You are a clinical safety judge reviewing four independent AI triage \
assessments of the same patient presentation. Your role is to identify \
consensus, note any clinically significant disagreements, and produce a final \
authoritative triage recommendation.

The four assessments are:
GPT-4o assessment: {gpt4o_response}
Claude assessment: {claude_response}
Gemini assessment: {gemini_response}
Mistral assessment: {mistral_response}

Instructions:
1. Identify the points all models agree on
2. Note any contradictions and their clinical significance
3. Apply the safety principle: when in doubt, escalate
4. Produce a final triage level: RED, AMBER, or GREEN
5. Provide a synthesised clinical reasoning combining the best insights from all four models
6. State your confidence level: HIGH, MEDIUM, or LOW
7. Flag if mandatory clinician review is required

Respond in this exact JSON format:
{{
  "final_triage": "RED/AMBER/GREEN",
  "confidence": "HIGH/MEDIUM/LOW",
  "consensus_summary": "what all models agreed on",
  "disagreements": "any contradictions found",
  "clinical_reasoning": "synthesised reasoning",
  "mandatory_review": true/false,
  "safety_flags": []
}}\
"""

_TRIAGE_LEVEL_RE = re.compile(r"\b(RED|AMBER|GREEN)\b")

_MODEL_TIMEOUT = 30  # seconds per model call


# ---------------------------------------------------------------------------
# Key resolution — graceful if keys missing
# ---------------------------------------------------------------------------

def _get_key(section: str, key: str, env_key: str) -> str | None:
    """Read a key from st.secrets (Streamlit Cloud) then os.getenv (.env)."""
    try:
        import streamlit as st  # noqa: PLC0415
        val = st.secrets[section][key]
        if val:
            return str(val)
    except Exception:
        pass
    return os.getenv(env_key) or None


def _resolve_keys() -> dict[str, str | None]:
    """Return all four API keys (value is None if not configured)."""
    return {
        "openai":    _get_key("openai",    "OPENAI_API_KEY",    "OPENAI_API_KEY"),
        "anthropic": _get_key("anthropic", "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        "gemini":    _get_key("gemini",    "GEMINI_API_KEY",    "GEMINI_API_KEY"),
        "mistral":   _get_key("mistral",   "MISTRAL_API_KEY",   "MISTRAL_API_KEY"),
    }


# ---------------------------------------------------------------------------
# Case formatter (mirrors rag_pipeline._format_similar_cases)
# ---------------------------------------------------------------------------

def _format_similar_cases(results: list) -> str:
    if not results:
        return "No similar cases found."
    parts: list[str] = []
    for i, (doc, score) in enumerate(results, 1):
        meta = doc.metadata
        parts.append(
            f"Case {i} (similarity {score:.2f}):\n"
            f"  Presentation: {doc.page_content[:300]}...\n"
            f"  Triage: {meta.get('triage_decision', 'Unknown')}\n"
            f"  Urgency: {meta.get('urgency_timeframe', 'Unknown')}\n"
            f"  Guideline: {meta.get('nice_guideline', 'Unknown')}\n"
            f"  Action: {meta.get('recommended_action', 'Unknown')}"
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Triage-level extractor
# ---------------------------------------------------------------------------

def _extract_triage_level(text: str) -> str:
    """Return the first RED/AMBER/GREEN found in text, defaulting to AMBER."""
    # Prioritise the labelled field
    match = re.search(r"TRIAGE_DECISION\s*:\s*(RED|AMBER|GREEN)", text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    match = _TRIAGE_LEVEL_RE.search(text)
    return match.group(1) if match else "AMBER"


# ---------------------------------------------------------------------------
# Per-model async callers
# ---------------------------------------------------------------------------

async def _call_gpt4o(prompt_messages: list[dict], api_key: str) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        from openai import AsyncOpenAI  # noqa: PLC0415
        client = AsyncOpenAI(api_key=api_key)
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o",
                messages=prompt_messages,
                temperature=0.0,
                max_tokens=1000,
            ),
            timeout=_MODEL_TIMEOUT,
        )
        text = resp.choices[0].message.content or ""
        return {
            "model": "GPT-4o",
            "response": text,
            "triage_level": _extract_triage_level(text),
            "response_time": round(time.monotonic() - t0, 2),
            "error": None,
        }
    except Exception as exc:
        return {
            "model": "GPT-4o",
            "response": "",
            "triage_level": None,
            "response_time": round(time.monotonic() - t0, 2),
            "error": str(exc),
        }


async def _call_claude(prompt_messages: list[dict], api_key: str) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        import anthropic  # noqa: PLC0415
        # Split system from user messages
        system_msg = next(
            (m["content"] for m in prompt_messages if m["role"] == "system"),
            _SYSTEM_PROMPT,
        )
        user_msgs = [m for m in prompt_messages if m["role"] != "system"]
        client = anthropic.AsyncAnthropic(api_key=api_key)
        resp = await asyncio.wait_for(
            client.messages.create(
                model="claude-opus-4-5",
                max_tokens=1000,
                system=system_msg,
                messages=user_msgs,
            ),
            timeout=_MODEL_TIMEOUT,
        )
        text = resp.content[0].text if resp.content else ""
        return {
            "model": "Claude",
            "response": text,
            "triage_level": _extract_triage_level(text),
            "response_time": round(time.monotonic() - t0, 2),
            "error": None,
        }
    except Exception as exc:
        return {
            "model": "Claude",
            "response": "",
            "triage_level": None,
            "response_time": round(time.monotonic() - t0, 2),
            "error": str(exc),
        }


async def _call_gemini(prompt_text: str, api_key: str) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        import google.genai as genai  # noqa: PLC0415
        client = genai.Client(api_key=api_key)
        resp = await asyncio.wait_for(
            client.aio.models.generate_content(
                model="gemini-1.5-pro",
                contents=prompt_text,
            ),
            timeout=_MODEL_TIMEOUT,
        )
        text = resp.text or ""
        return {
            "model": "Gemini",
            "response": text,
            "triage_level": _extract_triage_level(text),
            "response_time": round(time.monotonic() - t0, 2),
            "error": None,
        }
    except Exception as exc:
        return {
            "model": "Gemini",
            "response": "",
            "triage_level": None,
            "response_time": round(time.monotonic() - t0, 2),
            "error": str(exc),
        }


async def _call_mistral(prompt_messages: list[dict], api_key: str) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        from mistralai.client import Mistral  # noqa: PLC0415
        client = Mistral(api_key=api_key)
        # Mistral v2 SDK does not accept 'system' role — merge into first user msg
        user_msgs = []
        system_content = ""
        for m in prompt_messages:
            if m["role"] == "system":
                system_content = m["content"]
            else:
                user_msgs.append(m)
        if system_content and user_msgs:
            user_msgs[0] = {
                "role": "user",
                "content": f"{system_content}\n\n{user_msgs[0]['content']}",
            }
        resp = await asyncio.wait_for(
            client.chat.complete_async(
                model="mistral-large-latest",
                messages=user_msgs,
                temperature=0.0,
                max_tokens=1000,
            ),
            timeout=_MODEL_TIMEOUT,
        )
        text = resp.choices[0].message.content or ""
        return {
            "model": "Mistral",
            "response": text,
            "triage_level": _extract_triage_level(text),
            "response_time": round(time.monotonic() - t0, 2),
            "error": None,
        }
    except Exception as exc:
        return {
            "model": "Mistral",
            "response": "",
            "triage_level": None,
            "response_time": round(time.monotonic() - t0, 2),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Consensus calculation
# ---------------------------------------------------------------------------

def _calculate_consensus(
    results: list[dict[str, Any]],
) -> tuple[str, str, float, str]:
    """
    Returns (consensus_triage, consensus_type, agreement_score, safety_note).

    consensus_type: STRONG | WEAK | NONE
    agreement_score: 0.0 – 100.0
    """
    responding = [r for r in results if r.get("triage_level") and not r.get("error")]
    if not responding:
        return "AMBER", "NONE", 0.0, "No models responded — defaulting to AMBER for safety."

    votes: dict[str, list[str]] = {"RED": [], "AMBER": [], "GREEN": []}
    for r in responding:
        lvl = r["triage_level"]
        if lvl in votes:
            votes[lvl].append(r["model"])

    max_count = max(len(v) for v in votes.values())
    total = len(responding)
    agreement_score = (max_count / total) * 100

    # Winning level
    winner = max(votes, key=lambda k: len(votes[k]))

    # Consensus type
    if max_count >= 3:
        consensus_type = "STRONG"
    elif max_count == 2 and total >= 3:
        consensus_type = "WEAK"
    else:
        consensus_type = "NONE"

    # Safety escalation: if ANY model says RED and winner is not RED → override
    safety_note = ""
    if winner != "RED" and votes["RED"]:
        winner = "RED"
        models_said_red = ", ".join(votes["RED"])
        safety_note = (
            f"One or more models indicated RED ({models_said_red}) — "
            "escalated for patient safety."
        )

    return winner, consensus_type, round(agreement_score, 1), safety_note


# ---------------------------------------------------------------------------
# Judge model
# ---------------------------------------------------------------------------

async def _call_judge(
    model_results: dict[str, dict],
    api_key: str,
) -> tuple[dict[str, Any], float]:
    """Send all four responses to GPT-4o as judge. Returns (parsed_dict, elapsed)."""
    t0 = time.monotonic()
    prompt = _JUDGE_TEMPLATE.format(
        gpt4o_response=model_results.get("GPT-4o", {}).get("response") or "No response",
        claude_response=model_results.get("Claude", {}).get("response") or "No response",
        gemini_response=model_results.get("Gemini", {}).get("response") or "No response",
        mistral_response=model_results.get("Mistral", {}).get("response") or "No response",
    )
    judge_defaults: dict[str, Any] = {
        "final_triage": "AMBER",
        "confidence": "LOW",
        "consensus_summary": "Judge model failed to respond.",
        "disagreements": "Unknown",
        "clinical_reasoning": "Unable to synthesise — please review manually.",
        "mandatory_review": True,
        "safety_flags": ["Judge model error"],
    }
    try:
        from openai import AsyncOpenAI  # noqa: PLC0415
        client = AsyncOpenAI(api_key=api_key)
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1200,
                response_format={"type": "json_object"},
            ),
            timeout=_MODEL_TIMEOUT,
        )
        raw = resp.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        elapsed = round(time.monotonic() - t0, 2)
        return parsed, elapsed
    except Exception as exc:
        judge_defaults["safety_flags"] = [f"Judge model error: {exc}"]
        return judge_defaults, round(time.monotonic() - t0, 2)


# ---------------------------------------------------------------------------
# Main ensemble function
# ---------------------------------------------------------------------------

async def run_ensemble_triage(
    patient_presentation: str,
    similar_cases: list,
) -> dict[str, Any]:
    """
    Run a four-model ensemble triage and return a consensus result dict.

    Parameters
    ----------
    patient_presentation : str
        Free-form patient description.
    similar_cases : list
        (Document, score) pairs from VectorStore.search() — may be empty.

    Returns
    -------
    dict with keys:
        final_triage, confidence, agreement_score, consensus_type,
        mandatory_review, safety_flags, model_responses, judge_reasoning,
        disagreements, response_times, total_time,
        models_used, models_skipped
    """
    ensemble_start = time.monotonic()

    keys = _resolve_keys()
    similar_text = _format_similar_cases(similar_cases)
    human_content = _HUMAN_TEMPLATE.format(
        similar_cases=similar_text,
        patient_description=patient_presentation,
    )

    # Standard messages list (system + user)
    prompt_messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": human_content},
    ]
    # Gemini gets a single merged string
    gemini_prompt = f"{_SYSTEM_PROMPT}\n\n{human_content}"

    # ── Determine which models to include ───────────────────────────────────
    tasks: list[tuple[str, Any]] = []
    skipped: list[str] = []

    if keys["openai"]:
        tasks.append(("GPT-4o",  _call_gpt4o(prompt_messages, keys["openai"])))
    else:
        skipped.append("GPT-4o")

    if keys["anthropic"]:
        tasks.append(("Claude",  _call_claude(prompt_messages, keys["anthropic"])))
    else:
        skipped.append("Claude")

    if keys["gemini"]:
        tasks.append(("Gemini",  _call_gemini(gemini_prompt, keys["gemini"])))
    else:
        skipped.append("Gemini")

    if keys["mistral"]:
        tasks.append(("Mistral", _call_mistral(prompt_messages, keys["mistral"])))
    else:
        skipped.append("Mistral")

    active_count = len(tasks)

    # Minimum 2 models required — fall back to single-model warning if fewer
    if active_count < 2:
        return {
            "final_triage": "AMBER",
            "confidence": "LOW",
            "agreement_score": 0.0,
            "consensus_type": "NONE",
            "mandatory_review": True,
            "safety_flags": [
                f"Insufficient models configured ({active_count}/4). "
                "Please add API keys for at least 2 models."
            ],
            "model_responses": {},
            "judge_reasoning": "Ensemble requires at least 2 models.",
            "disagreements": "N/A",
            "response_times": {},
            "total_time": 0.0,
            "models_used": [t[0] for t in tasks],
            "models_skipped": skipped,
        }

    # ── Run all models in parallel ───────────────────────────────────────────
    results_list: list[dict] = await asyncio.gather(*(coro for _, coro in tasks))

    # Map model name → result
    model_results: dict[str, dict] = {
        name: res for (name, _), res in zip(tasks, results_list)
    }

    # ── Consensus ────────────────────────────────────────────────────────────
    consensus_triage, consensus_type, agreement_score, safety_note = (
        _calculate_consensus(results_list)
    )

    # ── Judge model ──────────────────────────────────────────────────────────
    judge_data: dict[str, Any] = {}
    judge_time = 0.0
    if keys["openai"]:
        judge_data, judge_time = await _call_judge(model_results, keys["openai"])
    else:
        judge_data = {
            "final_triage": consensus_triage,
            "confidence": "MEDIUM",
            "consensus_summary": "Judge model not available (OpenAI key missing).",
            "disagreements": "",
            "clinical_reasoning": "Consensus-based decision only.",
            "mandatory_review": consensus_type == "NONE",
            "safety_flags": ["Judge model unavailable"],
        }

    # The judge's final_triage takes precedence; apply safety escalation on top
    final_triage = judge_data.get("final_triage", consensus_triage).upper()
    if final_triage not in ("RED", "AMBER", "GREEN"):
        final_triage = consensus_triage

    # Safety escalation: if consensus or any model said RED, never downgrade
    all_levels = [r.get("triage_level") for r in results_list if r.get("triage_level")]
    if "RED" in all_levels and final_triage != "RED":
        final_triage = "RED"
        safety_flags = list(judge_data.get("safety_flags") or [])
        safety_flags.append(
            "Safety escalation: one or more models indicated RED — "
            "judge output overridden to RED."
        )
        judge_data["safety_flags"] = safety_flags

    safety_flags_out: list[str] = list(judge_data.get("safety_flags") or [])
    if safety_note:
        safety_flags_out.insert(0, safety_note)

    mandatory_review = bool(judge_data.get("mandatory_review", consensus_type == "NONE"))

    # ── Build model_responses summary ────────────────────────────────────────
    model_responses: dict[str, dict] = {}
    response_times: dict[str, float] = {}
    for name, res in model_results.items():
        response_times[name] = res.get("response_time", 0.0)
        raw_resp = res.get("response", "")
        # Extract a short summary (first 200 chars of clinical reasoning)
        summary_match = re.search(
            r"CLINICAL_REASONING\s*:\s*(.{0,200})", raw_resp, re.DOTALL
        )
        summary = (
            summary_match.group(1).strip()[:200]
            if summary_match
            else raw_resp[:200]
        )
        model_responses[name] = {
            "triage": res.get("triage_level") or "N/A",
            "summary": summary,
            "error": res.get("error"),
        }

    response_times["Judge"] = judge_time
    total_time = round(time.monotonic() - ensemble_start, 2)

    return {
        "final_triage":    final_triage,
        "confidence":      (judge_data.get("confidence") or "MEDIUM").upper(),
        "agreement_score": agreement_score,
        "consensus_type":  consensus_type,
        "mandatory_review": mandatory_review,
        "safety_flags":    safety_flags_out,
        "model_responses": model_responses,
        "judge_reasoning": judge_data.get("clinical_reasoning", ""),
        "disagreements":   judge_data.get("disagreements", ""),
        "consensus_summary": judge_data.get("consensus_summary", ""),
        "response_times":  response_times,
        "total_time":      total_time,
        "models_used":     list(model_results.keys()),
        "models_skipped":  skipped,
    }
