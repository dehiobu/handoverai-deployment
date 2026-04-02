"""
Vector store wrapper around ChromaDB + LangChain OpenAI embeddings.

Embeds in small batches (default: 5) to stay under project-level spending
caps and avoid 429 'insufficient_quota' errors. Already-embedded IDs are
skipped so the process is safe to re-run after interruption.

Public API (used by app.py and rag_pipeline.py):
    vector_store.initialize_from_json(dataset_path)  -- first-run setup
    vector_store.load_existing()                      -- load persisted store
    vector_store.search(query, k=None)                -- similarity search
"""

import json
import time
from typing import Any

import chromadb
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

import config
from src.chroma_config import CHROMA_SETTINGS
from src.openai_http import create_openai_http_clients


class VectorStore:
    """
    Vector store builder with safe chunked embedding to avoid quota spikes.
    This version embeds in small batches (default: 5) to stay under project-level
    spending caps and avoid 429 'insufficient_quota' errors.
    """

    def __init__(self) -> None:
        self._vectorstore: Chroma | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_embeddings(self) -> OpenAIEmbeddings:
        http_client, async_http_client = create_openai_http_clients()
        return OpenAIEmbeddings(
            openai_api_key=config.OPENAI_API_KEY,
            model=config.EMBEDDING_MODEL,
            http_client=http_client,
            http_async_client=async_http_client,
        )

    def _get_chroma_client(self) -> chromadb.PersistentClient:
        return chromadb.PersistentClient(
            path=str(config.CHROMA_DIR),
            settings=CHROMA_SETTINGS,
        )

    def _load_cases(self, dataset_path: str) -> list[dict]:
        """Load and normalise the dataset JSON.

        Accepts either a flat list of cases or a dict with a 'presentations' key.
        """
        with open(dataset_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "presentations" in data:
            return data["presentations"]
        raise ValueError(
            "Unexpected dataset format: expected a JSON list or a dict "
            "with a 'presentations' key."
        )

    def _case_to_text(self, case: dict) -> str:
        """Flatten a case dict into a single searchable string."""
        symptoms = ", ".join(case.get("symptoms", []))
        pmh = ", ".join(case.get("past_medical_history", []))
        red_flags = ", ".join(case.get("red_flags_present", []))
        return (
            f"{case.get('patient_description', '')} "
            f"Chief complaint: {case.get('chief_complaint', '')}. "
            f"Age: {case.get('age', '')} {case.get('gender', '')}. "
            f"Symptoms: {symptoms}. "
            f"Duration: {case.get('duration', '')}. "
            f"PMH: {pmh}. "
            f"Red flags: {red_flags}. "
            f"Triage: {case.get('triage_decision', '')}. "
            f"Reasoning: {case.get('clinical_reasoning', '')}."
        )

    def _case_to_metadata(self, case: dict, index: int) -> dict:
        """Extract the metadata stored alongside each Chroma document."""
        return {
            "case_id": str(case.get("id", f"case_{index}")),
            "triage_decision": str(case.get("triage_decision", "")),
            "urgency_timeframe": str(case.get("urgency_timeframe", "")),
            "chief_complaint": str(case.get("chief_complaint", "")),
            "nice_guideline": str(case.get("nice_guideline", "")),
            "recommended_action": str(case.get("recommended_action", "")),
            "confidence": str(case.get("confidence", "")),
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def initialize_from_json(self, dataset_path: str, batch_size: int = 5) -> None:
        """Build the ChromaDB vector store from the dataset JSON.

        Embeds in small batches to avoid quota spikes.
        """
        cases = self._load_cases(dataset_path)
        total = len(cases)

        texts: list[str] = []
        metadatas: list[dict] = []
        ids: list[str] = []

        for i, case in enumerate(cases):
            texts.append(self._case_to_text(case))
            metadatas.append(self._case_to_metadata(case, i))
            ids.append(str(case.get("id", f"case_{i}")))

        embeddings = self._get_embeddings()
        client = self._get_chroma_client()

        # Create or load collection
        collection = client.get_or_create_collection(
            name=config.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        print(f"[INFO] Total cases to embed: {total}", flush=True)

        # Process in safe chunks
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            print(f"[INFO] Embedding cases {start + 1}-{end} of {total}...", flush=True)

            batch_texts = texts[start:end]
            batch_metas = metadatas[start:end]
            batch_ids = ids[start:end]

            # Skip already embedded items
            existing = set(collection.get(ids=batch_ids).get("ids", []))
            new_texts = []
            new_metas = []
            new_ids = []

            for t, m, id_ in zip(batch_texts, batch_metas, batch_ids):
                if id_ not in existing:
                    new_texts.append(t)
                    new_metas.append(m)
                    new_ids.append(id_)

            if not new_ids:
                print("[INFO] Batch already embedded, skipping.", flush=True)
                continue

            # Retry wrapper
            for attempt in range(5):
                try:
                    response = embeddings.embed_documents(new_texts)
                    collection.add(
                        ids=new_ids,
                        embeddings=response,
                        documents=new_texts,
                        metadatas=new_metas,
                    )
                    break
                except Exception as e:
                    print(f"[WARN] Embedding batch failed: {e}", flush=True)
                    time.sleep(2 ** attempt)
            else:
                raise RuntimeError("Failed to embed batch after retries.")

        print(f"[SUCCESS] All {total} cases embedded.", flush=True)
        self.load_existing()

    def load_existing(self) -> None:
        """Attach to an already-built ChromaDB store without re-embedding."""
        embeddings = self._get_embeddings()
        client = self._get_chroma_client()

        self._vectorstore = Chroma(
            client=client,
            collection_name=config.COLLECTION_NAME,
            embedding_function=embeddings,
        )

    def search(self, query: str, k: int | None = None) -> list[tuple[Any, float]]:
        """Return the top-k most similar cases as (Document, score) pairs."""
        if self._vectorstore is None:
            raise RuntimeError(
                "Vector store is not initialised. "
                "Call initialize_from_json() or load_existing() first."
            )
        if k is None:
            k = config.SIMILARITY_TOP_K
        return self._vectorstore.similarity_search_with_score(query, k=k)


# Module-level singleton imported by app.py:
#   from src.vector_store import vector_store
vector_store = VectorStore()