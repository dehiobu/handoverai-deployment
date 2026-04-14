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
| Phase 8 | SQLite persistence — `gp_triage.db` stores all patient data across sessions; dashboard shows all-time historical stats; pathways reload from DB on startup |
| Phase 9 | Path A ward features — Daily Ward Log (SOAP), Nurse Observations (NEWS2 auto-scoring), Medication Administration Record (MAR), Safeguarding Flags (DAMA form + Social Services referral letter), Discharge Planning Checklist (13-item sign-off gating Stage 10), Patient Journey Timeline |

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
├── gp_triage.db                # SQLite database (generated, not committed — see .gitignore)
├── scripts/
│   ├── setup_vectorstore.py    # One-time CLI to build / rebuild the vector store
│   └── seed_demo_data.py       # Inserts 5 complete demo patient journeys + ward data
├── src/
│   ├── __init__.py
│   ├── chroma_config.py        # Shared ChromaDB Settings object
│   ├── database.py             # SQLite persistence layer (13 tables, 25+ functions)
│   ├── letter_generator.py     # NHS-branded Word document generator (referral, admission, diagnosis, discharge, DAMA, safeguarding referral, discharge checklist)
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
| `app.py` | Thin entry point: page config, NHS CSS, session state init, `init_db()`, `load_pathways_from_db()`, system initialisation, tab wiring |
| `config.py` | Centralized config: paths, OpenAI models, RAG parameters, triage level constants |
| `tabs/triage_tab.py` | Triage tab UI and logic: input, RAG call, result display, history (Phases 1-4) |
| `tabs/dashboard_tab.py` | Executive metrics dashboard: KPIs, charts, all-time DB stats, ward overview, audit log, CSV/JSON export (Phases 3, 5, 8 & 9) |
| `tabs/governance_tab.py` | About & Governance tab: how AI works, data handling, FHIR roadmap, approvals (Phase 6) |
| `tabs/pathway_tab.py` | 10-stage Patient Pathway Tracker + Ward Management (Daily Log, NEWS2 Observations, MAR, Safeguarding, Discharge Checklist, Timeline) — saves all stages to DB (Phases 7 & 9) |
| `ui/components.py` | Reusable components: `render_explainability_panel()`, `show_result()`, `OVERRIDE_REASONS` |
| `ui/sidebar.py` | Sidebar: `DEMO_SCENARIOS`, `render_sidebar()` — demo picker, system info, session metrics |
| `src/database.py` | SQLite persistence: 13 tables, `init_db()`, CRUD functions, `load_pathways_from_db()`, `get_ward_overview_stats()`, `get_patient_timeline()` |
| `src/letter_generator.py` | NHS-branded Word documents: referral, admission, diagnosis, discharge, DAMA form, safeguarding referral, discharge checklist |
| `src/vector_store.py` | ChromaDB wrapper: loads JSON dataset, generates embeddings in batches, runs similarity search |
| `src/rag_pipeline.py` | RAG orchestration: retrieves similar cases, builds prompt, calls GPT-4o, parses response, extracts explainability data |
| `src/openai_http.py` | Creates paired sync/async httpx clients injected into LangChain to avoid `proxies` crash |
| `src/chroma_config.py` | Shared `chroma.Settings` (allow_reset, telemetry off) — must be used everywhere Chroma is instantiated |
| `scripts/setup_vectorstore.py` | One-time CLI to build `chroma_db/` from the dataset |
| `scripts/seed_demo_data.py` | Inserts 5 demo patient journeys + ward logs, observations, medications, safeguarding flags, discharge checklists |

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

## Database Architecture (`src/database.py`)

SQLite database at `gp_triage.db` in the project root. Uses Python's built-in `sqlite3` only — no extra packages. WAL journal mode for concurrent reads.

### Tables

| Table | Purpose |
|---|---|
| `patients` | Patient demographics: nhs_number (UNIQUE), age, gender, description |
| `triage_sessions` | AI triage results: decision, urgency, reasoning, red flags, confidence, response time, override |
| `assignments` | Doctor/specialty assignments per patient |
| `referrals` | Imaging and blood test referrals |
| `pathway_stages` | All 10 pathway stages with JSON blob of stage data (UNIQUE per nhs_number+stage_number) |
| `letters` | Generated letter metadata and content |
| `audit_log` | All clinical actions with performer and timestamp |
| `ward_logs` | SOAP ward round entries per shift (Path A) |
| `nurse_observations` | Per-shift vitals with auto-calculated NEWS2 score (Path A) |
| `medications` | Medication Administration Record (MAR) entries (Path A) |
| `safeguarding_flags` | Safeguarding concerns with flag type, action, referral (Path A) |
| `discharge_checklist` | 13-item pre-discharge sign-off state per patient (Path A) |

### Startup sequence

```python
# app.py — runs once per browser session (session state guard)
init_db()                              # CREATE TABLE IF NOT EXISTS (idempotent)
st.session_state.pathways = load_pathways_from_db()   # pre-populate pathway tracker
```

### Seeding demo data

```bash
python scripts/seed_demo_data.py
# Safe to re-run — skips already-seeded patients via ON CONFLICT / existence check
```

Seeds 5 complete patient journeys: Dennis E (Acute MI), Child 8F (Bacterial Meningitis), Sarah M (Pyelonephritis), James K (Severe Depression — still admitted), Emma T (Viral Tonsillitis — same-day discharge). Each patient has 3 ward logs, 2 observation sets, medications, and discharge checklists where applicable. Patient 2 has a child protection safeguarding flag. Patient 4 has an MCA concern flag.

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
