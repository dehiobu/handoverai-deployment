## GP Triage POC – Deep Dive

This README explains the project end‑to‑end: what it does, how the components interact, and what technologies are in play. Treat it as a study guide that you can revisit whenever you need to reason about the architecture or teach it to someone else.

---

### 1. Purpose

The project is a **Retrieval-Augmented Generation (RAG)** prototype for GP triage:

- **Input**: Free-form patient presentation text.
- **Retrieval**: Retrieve similar cases (447 AI-validated clinical cases) from a ChromaDB vector store.
- **Generation**: Use OpenAI’s GPT-4o via LangChain to synthesize a triage decision (RED/AMBER/GREEN), urgency, reasoning, red flags, NICE references, and recommended actions.
- **Interface**: A Streamlit UI that guides the user through entry, triage, and review history.

It’s intentionally scoped for experimentation and validation—not production—but it reflects a realistic RAG workflow.

---

### 2. Tech Stack

| Layer | Details |
| --- | --- |
| **Language** | Python 3.11.x |
| **App Framework** | Streamlit 1.29.0 |
| **RAG Orchestration** | LangChain 0.1.20 (with `langchain-core`, `langchain-openai`, `langchain-community`) |
| **Vector DB** | ChromaDB 0.4.22 (persistent SQLite store) |
| **LLM** | OpenAI GPT-4o for chat, `text-embedding-3-small` for embeddings |
| **Dataset** | `data/ai_validated_dataset.json` (447 cases with patient data, reasoning, NICE cites, etc.) |
| **Environment Management** | `.env` + `python-dotenv` for API keys and model tuning |

---

### 3. Data Shape (JSON Case)

Each entry in `data/ai_validated_dataset.json` is a dictionary. Either `{"presentations": [...]}` or a flat list is supported. A typical case includes:

```jsonc
{
  "id": "case_123",
  "patient_description": "64-year-old male with crushing chest pain...",
  "chief_complaint": "Chest pain",
  "age": 64,
  "gender": "male",
  "symptoms": [
    "Crushing chest pain",
    "Pain radiating left arm",
    "Sweating",
    "Nausea"
  ],
  "duration": "40 minutes",
  "triage_decision": "RED",
  "urgency_timeframe": "999 now",
  "clinical_reasoning": "Presentation is classic for acute coronary syndrome...",
  "red_flags_present": [
    "Chest pain + diaphoresis",
    "Radiation to left arm"
  ],
  "past_medical_history": [
    "Hypertension"
  ],
  "nice_guideline": "NG185 – Acute coronary syndromes",
  "recommended_action": "Immediate ambulance to ED",
  "confidence": "High"
}
```

`src/vector_store.VectorStore` flattens each case into an indexed text blob with metadata (`case_id`, `system`, `triage_decision`, etc.), making retrieval explainable.

---

### 4. Key Components

#### `src/vector_store.py`
1. **Embeddings**: Uses `OpenAIEmbeddings` with explicit HTTPX clients (via `src/openai_http.py`) so httpx 0.28+ works.
2. **Chroma Client**: Instantiated with shared `CHROMA_SETTINGS` (allow_reset, telemetry off).  
3. **Initialize from JSON**: Reads dataset, builds texts+metadata, and calls `Chroma.from_texts(...)`.
4. **Search**: Wrapper over `vectorstore.similarity_search_with_score`.

#### `src/rag_pipeline.py`
1. Accepts a `VectorStore`.
2. Retrieves top-`k` similar cases (`SIMILARITY_TOP_K`).
3. Constructs contextual prompt using `langchain.prompts.ChatPromptTemplate`.
4. Invokes `ChatOpenAI` with custom HTTPX clients for GPT-4o.
5. Post-processes the raw response via regex into a structured dictionary returned to Streamlit.

#### `app.py`
1. Streamlit UI with custom CSS and friendly instructions.
2. Handles state initialization (vector store + RAG pipeline).
3. Provides input area, sample cases, and a “Triage Patient” button.
4. Displays results, red flags, NICE references, confidence, history, and raw LLM response in expandable sections.

#### `scripts/setup_vectorstore.py`
1. Pre-flight CLI script to build the ChromaDB store from the dataset.
2. Optional reset path (with shared Chroma settings) to clear old stores.
3. ASCII-only logging so Windows consoles don’t throw Unicode errors.

#### `src/openai_http.py`
Ensures every LangChain OpenAI client gets an explicit sync + async HTTPX client to avoid `proxies` keyword errors (introduced in httpx 0.28).

#### `src/chroma_config.py`
Shared Chroma `Settings` – we pass this everywhere to prevent mismatched configurations when multiple processes (setup script + Streamlit) use the same SQLite store.

---

### 5. Flow Overview

1. **Setup**  
   - `python -m venv venv`  
   - `pip install -r requirements.txt`  
   - Configure `.env` with a valid `OPENAI_API_KEY`, models, etc.  
   - Run `python scripts/setup_vectorstore.py` to build `chroma_db/`.

2. **Runtime**  
   - `streamlit run app.py`  
   - Enter patient description; click “Triage Patient”.  
   - The app:
     1. Pulls similar cases from Chroma.
     2. Sends context + patient description to GPT-4o.
     3. Parses the structured output and renders it nicely.

3. **Iteration**  
   - For dataset changes, rerun the setup script and answer “yes” to reset.  
   - Developers can inspect `src/vector_store.py` or `src/rag_pipeline.py` to tweak prompt logic, retrieval parameters, or the metadata structure.

---

### 6. Learning Checklist

- **Understand RAG**: retrieval → prompt construction → LLM generation → parsing.
- **Chroma usage**: persistent client, metadata, `.reset()` vs manual deletes.
- **LangChain**: prompt templates, `ChatOpenAI`, `OpenAIEmbeddings`, handling breaking changes (httpx 0.28).
- **Streamlit UX**: session state, expanders, spinners, columns.
- **Operational concerns**: environment keys, dataset validation, Windows file locks, repeating telemetry warnings.

With this foundation you can:
- Swap GPT models (update `.env` + `config.py` defaults).
- Tune retrieval depth (`SIMILARITY_TOP_K`).
- Enrich metadata (e.g., add more patient attributes).
- Replace AI-validated data with clinician-validated data without touching most of the pipeline.

Use this reference when onboarding collaborators or when you come back to extend the POC later. It documents not just what the project does, but *why* each piece exists and how they interrelate.***
