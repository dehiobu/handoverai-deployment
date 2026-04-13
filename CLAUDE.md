# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GP Triage POC is a **Retrieval-Augmented Generation (RAG)** prototype for GP medical triage, enhanced for NHS showcase to three audiences: Executives, GPs/Clinicians, and IT/IG teams. It is explicitly scoped for experimentation/validation and **not for clinical production use**.

- **Input**: Free-form patient presentation text (or pre-loaded demo scenarios)
- **Retrieval**: Finds top-5 similar cases from 447 AI-validated clinical cases in ChromaDB
- **Generation**: GPT-4o synthesizes a triage decision (RED/AMBER/GREEN), urgency, reasoning, red flags, NICE references, and recommended actions
- **Explainability**: Top-3 matched cases shown with similarity scores and plain-English confidence
- **Interface**: Four-tab Streamlit UI — Triage, Patient Pathway, Dashboard, About & Governance
- **Audit**: Full session audit log exportable as JSON or CSV; clinician overrides with dropdown reason
- **Pathway Tracker**: 10-stage end-to-end clinical pathway from presentation to discharge

### Showcase Phases

| Phase | Feature |
|---|---|
| Phase 1 | NHS colour scheme (#005EB8/#DA291C/#FFB81C/#009639), safety banner, professional layout |
| Phase 2 | Explainability panel — top-3 matched cases with similarity bars, plain-English confidence |
| Phase 3 | Enhanced audit log — CSV export, override reason dropdown, summary stats |
| Phase 4 | Demo scenarios — 5 pre-loaded clinical scenarios auto-fill the input |
| Phase 5 | Executive metrics dashboard — KPIs, distribution chart, override trend, time-saved estimate |
| Phase 6 | Governance panel — how AI works, data handling, audit capabilities, FHIR roadmap, approvals checklist |
| Phase 7 | Patient Pathway Tracker — 10-stage end-to-end pathway (Presentation → Triage → Assignment → Referral → Admission → Diagnosis → Treatment → Outcome → Aftercare → Discharge) with auto-fill, clinical letters, and full JSON/CSV export |

## Folder Structure

```
gp-triage-poc/
├── app.py                      # Thin Streamlit entry point: page config, CSS, session state, tab wiring
├── config.py                   # Centralised settings (paths, models, constants)
├── requirements.txt
├── data/
│   └── ai_validated_dataset.json   # 447 AI-validated clinical cases
├── chroma_db/                  # ChromaDB persistence (generated, not committed)
├── images/
│   └── Logo.png                # NHS branding asset used in the UI
├── logs/                       # Runtime log files (generated)
├── scripts/
│   └── setup_vectorstore.py    # One-time CLI to build / rebuild the vector store
├── src/
│   ├── __init__.py
│   ├── chroma_config.py        # Shared ChromaDB Settings object
│   ├── openai_http.py          # Explicit httpx clients injected into LangChain
│   ├── rag_pipeline.py         # RAG orchestration + LLM call + response parsing
│   └── vector_store.py         # ChromaDB wrapper: embed, store, search
├── tabs/
│   ├── __init__.py
│   ├── triage_tab.py           # Triage tab UI and logic (Phases 1-4)
│   ├── dashboard_tab.py        # Executive metrics dashboard tab (Phases 3, 5 & 7)
│   ├── governance_tab.py       # About & Governance tab (Phase 6)
│   └── pathway_tab.py          # 10-stage Patient Pathway Tracker (Phase 7)
├── ui/
│   ├── __init__.py
│   ├── components.py           # Reusable components: triage card, explainability panel, override form
│   └── sidebar.py              # Sidebar: demo scenarios, system info, session metrics
└── tests/
    ├── conftest.py             # Shared fixtures; sets OPENAI_API_KEY=test-key
    ├── test_vector_store.py    # Unit tests for VectorStore pure functions
    └── test_rag_pipeline.py    # Unit tests for response parsing helpers
```

## Setup

```bash
# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate         # Windows
source venv/bin/activate       # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env         # Windows
cp .env.example .env           # Mac/Linux
# Edit .env and add OPENAI_API_KEY

# Place the dataset
# Copy ai_validated_dataset.json into data/

# Build the vector store (takes 5-10 minutes for 447 cases)
python scripts/setup_vectorstore.py
```

## Running

```bash
streamlit run app.py
# Opens at http://localhost:8501
```

## Running Tests

```bash
# All unit tests (no API key or vector store required)
pytest

# With verbose output
pytest -v

# A single file
pytest tests/test_rag_pipeline.py -v
```

Tests live in `tests/` and only cover pure-function logic (JSON parsing, text formatting, response parsing). No OpenAI calls are made. `conftest.py` sets a dummy `OPENAI_API_KEY` so `config.py` doesn't raise on import.

To **rebuild the vector store** after dataset changes:
```bash
python scripts/setup_vectorstore.py
# Answer "yes" at the prompt to reset and rebuild
```

## Architecture

### Module Responsibilities

| Module | Role |
|---|---|
| `app.py` | Thin entry point: page config, NHS CSS, session state init, system initialisation, tab wiring |
| `config.py` | Centralized config: paths, OpenAI models, RAG parameters, triage level constants |
| `tabs/triage_tab.py` | Triage tab UI and logic: input, RAG call, result display, history (Phases 1-4) |
| `tabs/dashboard_tab.py` | Executive metrics dashboard: KPIs, charts, audit log table, CSV/JSON export (Phases 3 & 5) |
| `tabs/governance_tab.py` | About & Governance tab: how AI works, data handling, FHIR roadmap, approvals (Phase 6) |
| `tabs/pathway_tab.py` | 10-stage Patient Pathway Tracker: visual stepper, auto-fill stages 1-4, forms for stages 5-10, clinical letters (Diagnosis + Discharge), full pathway JSON/CSV export (Phase 7) |
| `ui/components.py` | Reusable components: `render_explainability_panel()`, `show_result()`, `OVERRIDE_REASONS` |
| `ui/sidebar.py` | Sidebar: `DEMO_SCENARIOS`, `render_sidebar()` — demo picker, system info, session metrics |
| `src/vector_store.py` | ChromaDB wrapper: loads JSON dataset, generates embeddings in batches, runs similarity search |
| `src/rag_pipeline.py` | RAG orchestration: retrieves similar cases, builds prompt, calls GPT-4o, parses response, extracts explainability data |
| `src/openai_http.py` | Creates paired sync/async httpx clients injected into LangChain to avoid `proxies` crash |
| `src/chroma_config.py` | Shared `chroma.Settings` (allow_reset, telemetry off) — must be used everywhere Chroma is instantiated |
| `scripts/setup_vectorstore.py` | One-time CLI to build `chroma_db/` from the dataset |

### Data Flow

```
User input (patient description)  ← or auto-filled from sidebar demo scenario
    → VectorStore.search()              # top-5 similar cases from ChromaDB
    → RAGPipeline: build prompt         # retrieved cases + patient input
    → ChatOpenAI (GPT-4o)
    → regex parse → structured dict
    → _extract_similar_cases_data()     # top-3 cases for explainability panel
    → Streamlit display:
        - Colour-coded triage card (NHS RED/AMBER/GREEN)
        - Explainability panel (top-3 matched cases, similarity bars, plain-English confidence)
        - Clinical detail (reasoning, red flags, NICE, differentials)
        - Per-case JSON + CSV export
        - Clinician override form (dropdown reason, captured in audit log)
    → session audit log (exportable as JSON or CSV from Dashboard tab)
```

### Dataset Schema (`data/ai_validated_dataset.json`)

The file can be `{"presentations": [...]}` or a flat list. Each case contains:
- `patient_description`, `chief_complaint`, `age`, `gender`, `symptoms`, `duration`
- `triage_decision` (RED/AMBER/GREEN), `urgency_timeframe`
- `clinical_reasoning`, `red_flags_present`, `nice_guideline`, `recommended_action`, `confidence`
- `past_medical_history`

`VectorStore` flattens each case into an indexed text blob with metadata (`case_id`, `triage_decision`, etc.) for explainable retrieval.

## Key Configuration (`config.py`)

| Setting | Default | Purpose |
|---|---|---|
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embeddings model |
| `CHAT_MODEL` | `gpt-4o` | LLM for triage generation |
| `TEMPERATURE` | `0.0` | Deterministic outputs |
| `SIMILARITY_TOP_K` | `5` | Cases retrieved per query |
| `COLLECTION_NAME` | `gp_triage_cases` | ChromaDB collection name |

## Critical Compatibility Notes (httpx 0.28+)

LangChain's `OpenAIEmbeddings` and `ChatOpenAI` forward a legacy `proxies=` kwarg that httpx ≥ 0.28 removed. The fix is in `src/openai_http.py`: always inject explicit `http_client`/`http_async_client` when constructing these objects.

```python
http_client, async_http_client = create_openai_http_clients()
OpenAIEmbeddings(..., http_client=http_client, http_async_client=async_http_client)
ChatOpenAI(..., http_client=http_client, http_async_client=async_http_client)
```

Never instantiate `OpenAIEmbeddings` or `ChatOpenAI` without this helper.

## Windows-Specific Notes

- **Log output**: Keep all script output ASCII-only (use `[INFO]`/`[SUCCESS]` tags, not emoji). Windows default code page can't render emoji and will raise `UnicodeEncodeError`.
- **ChromaDB reset**: Never use `shutil.rmtree` on `chroma_db/` while any Python process has it open — this causes `[WinError 32]`. Use `PersistentClient(..., allow_reset=True).reset()` with the shared `CHROMA_SETTINGS` instead.
- **Chroma settings**: Always import `CHROMA_SETTINGS` from `src/chroma_config.py` when creating any Chroma client. Mismatched settings between processes cause "instance already exists with different settings" errors.

## Tested Dependency Versions

The following constraint ranges are known to work together on Python 3.12+:

| Package | Constraint |
|---|---|
| `langchain` | `>=0.2.0,<0.3` |
| `langchain-openai` | `>=0.1.8,<0.2` |
| `langchain-community` | `>=0.2.0,<0.3` |
| `langchain-core` | `>=0.2.0,<0.3` |
| `langchain-chroma` | `>=0.1.0,<0.2` |
| `openai` | `>=1.14.0,<2.0` |
| `httpx` | `>=0.27.0,<1.0` |
| `chromadb` | `0.4.22` |
| `streamlit` | `1.29.0` |

`langchain-openai>=0.1.8` fixed the legacy `proxies=` kwarg, so `src/openai_http.py` is no longer strictly required — but the explicit http client injection is kept for clean resource management.
