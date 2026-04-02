"""
Vector store wrapper around ChromaDB + LangChain OpenAI embeddings.

Public API (used by app.py and rag_pipeline.py):
    vector_store.initialize_from_json(dataset_path)  -- first-run setup
    vector_store.load_existing()                      -- load persisted store
    vector_store.search(query, k=None)                -- similarity search
"""
import json
import time
from pathlib import Path
from typing import Any

import chromadb
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

import config
from src.chroma_config import CHROMA_SETTINGS
from src.openai_http import create_openai_http_clients


class VectorStore:
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

    def initialize_from_json(self, dataset_path: str, batch_size: int = 50) -> None:
        """Build the ChromaDB vector store from the dataset JSON.

        Processes cases in batches and prints ASCII progress so the terminal
        shows activity during the embedding calls.
        """
        cases = self._load_cases(dataset_path)
        total = len(cases)

        texts: list[str] = []
        metadatas: list[dict] = []
        for i, case in enumerate(cases):
            texts.append(self._case_to_text(case))
            metadatas.append(self._case_to_metadata(case, i))

        embeddings = self._get_embeddings()
        client = self._get_chroma_client()

        # First batch: create the collection via from_texts
        first_end = min(batch_size, total)
        print(f"[INFO] Embedding cases 1-{first_end} of {total}...", flush=True)
        self._vectorstore = Chroma.from_texts(
            texts=texts[:first_end],
            embedding=embeddings,
            metadatas=metadatas[:first_end],
            client=client,
            collection_name=config.COLLECTION_NAME,
        )

        # Remaining batches: add_texts into the existing collection
        for start in range(first_end, total, batch_size):
            end = min(start + batch_size, total)
            print(f"[INFO] Embedding cases {start + 1}-{end} of {total}...", flush=True)
            time.sleep(1)
            self._vectorstore.add_texts(
                texts=texts[start:end],
                metadatas=metadatas[start:end],
            )

        print(f"[SUCCESS] All {total} cases embedded.", flush=True)

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
