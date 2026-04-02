"""
RAG pipeline: retrieve similar cases, build prompt, call GPT-4o, parse output.

Public API (used by app.py):
    pipeline = RAGPipeline(vector_store)
    result   = pipeline.triage_patient(patient_description)

Result dict keys
----------------
    triage_decision       -- RED | AMBER | GREEN
    urgency_timeframe     -- e.g. "999 now", "GP same day", "Routine appointment"
    clinical_reasoning    -- detailed LLM reasoning
    red_flags             -- flagged dangers or "None identified"
    nice_guideline        -- referenced NICE guideline
    recommended_action    -- what to do next
    differentials         -- differential diagnoses
    rule_out              -- conditions to rule out first
    follow_up_questions   -- questions to ask the patient
    confidence            -- High | Medium | Low + explanation
    similar_cases_count   -- number of retrieved cases used as context
    similar_cases         -- top-3 retrieved cases as dicts (for explainability panel)
    raw_response          -- unprocessed LLM output (for the expandable panel)
"""
import re

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

import config
from src.openai_http import create_openai_http_clients
from src.vector_store import VectorStore

# ---------------------------------------------------------------------------
# Prompt template
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

_HUMAN_PROMPT = """\
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


# ---------------------------------------------------------------------------
# Helper: format retrieved cases for the prompt
# ---------------------------------------------------------------------------

def _format_similar_cases(results: list) -> str:
    """Convert (Document, score) pairs into a readable block for the prompt."""
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
# Helper: parse structured LLM output
# ---------------------------------------------------------------------------

_FIELD_PATTERN = re.compile(
    r"^([A-Z_]+):\s*(.+?)(?=\n[A-Z_]+:|$)",
    re.MULTILINE | re.DOTALL,
)

_LABEL_MAP = {
    "TRIAGE_DECISION": "triage_decision",
    "URGENCY_TIMEFRAME": "urgency_timeframe",
    "CLINICAL_REASONING": "clinical_reasoning",
    "RED_FLAGS": "red_flags",
    "NICE_GUIDELINE": "nice_guideline",
    "RECOMMENDED_ACTION": "recommended_action",
    "DIFFERENTIALS": "differentials",
    "RULE_OUT": "rule_out",
    "FOLLOW_UP_QUESTIONS": "follow_up_questions",
    "CONFIDENCE": "confidence",
}

_DEFAULTS = {
    "triage_decision": "AMBER",
    "urgency_timeframe": "Urgent — requires clinical review",
    "clinical_reasoning": "Unable to parse clinical reasoning from response.",
    "red_flags": "Unable to determine — please review manually.",
    "nice_guideline": "Refer to relevant NICE guidelines.",
    "recommended_action": "Clinical review required.",
    "differentials": "Not specified.",
    "rule_out": "Not specified.",
    "follow_up_questions": "Not specified.",
    "confidence": "Low — response parsing failed.",
}


def _extract_similar_cases_data(results: list) -> list[dict]:
    """Extract the top-3 retrieved cases as structured dicts for the explainability panel.

    Each dict contains rank, similarity score/percentage, a short presentation
    snippet, and the key metadata fields from the matched case.
    """
    cases = []
    for rank, (doc, score) in enumerate(results[:3], 1):
        meta = doc.metadata
        cases.append({
            "rank": rank,
            "similarity_score": round(float(score), 4),
            "similarity_pct": round(float(score) * 100, 1),
            "presentation_snippet": doc.page_content[:250],
            "triage_decision": meta.get("triage_decision", "Unknown"),
            "urgency_timeframe": meta.get("urgency_timeframe", "Unknown"),
            "chief_complaint": meta.get("chief_complaint", "Unknown"),
            "nice_guideline": meta.get("nice_guideline", "Unknown"),
            "recommended_action": meta.get("recommended_action", "Unknown"),
        })
    return cases


def _parse_response(raw: str) -> dict:
    """Extract labelled fields from the LLM response into a result dict."""
    result = dict(_DEFAULTS)

    for match in _FIELD_PATTERN.finditer(raw):
        label = match.group(1).strip()
        value = match.group(2).strip()
        key = _LABEL_MAP.get(label)
        if key:
            result[key] = value

    # Normalise triage_decision to uppercase and validate
    decision = result["triage_decision"].upper()
    if decision not in config.TRIAGE_LEVELS:
        # Attempt fuzzy extraction
        for level in config.TRIAGE_LEVELS:
            if level in decision:
                decision = level
                break
        else:
            decision = "AMBER"
    result["triage_decision"] = decision

    return result


# ---------------------------------------------------------------------------
# RAGPipeline
# ---------------------------------------------------------------------------

class RAGPipeline:
    def __init__(self, vector_store: VectorStore) -> None:
        self._vector_store = vector_store

        http_client, async_http_client = create_openai_http_clients()
        self._llm = ChatOpenAI(
            openai_api_key=config.OPENAI_API_KEY,
            model=config.CHAT_MODEL,
            temperature=config.TEMPERATURE,
            max_tokens=config.MAX_TOKENS,
            http_client=http_client,
            http_async_client=async_http_client,
        )

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", _SYSTEM_PROMPT),
            ("human", _HUMAN_PROMPT),
        ])

    def triage_patient(self, patient_description: str) -> dict:
        """Run the full RAG pipeline for a patient description.

        1. Retrieve the top-k most similar validated cases from ChromaDB.
        2. Build a contextual prompt including those cases.
        3. Call GPT-4o.
        4. Parse and return a structured result dict.
        """
        # 1. Retrieve
        similar = self._vector_store.search(patient_description)
        similar_cases_text = _format_similar_cases(similar)

        # 2. Build prompt and call LLM
        chain = self._prompt | self._llm
        response = chain.invoke({
            "similar_cases": similar_cases_text,
            "patient_description": patient_description,
        })
        raw_response = response.content

        # 3. Parse
        result = _parse_response(raw_response)
        result["similar_cases_count"] = len(similar)
        result["similar_cases"] = _extract_similar_cases_data(similar)
        result["raw_response"] = raw_response

        return result
