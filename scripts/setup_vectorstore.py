"""
One-time CLI script to build (or rebuild) the ChromaDB vector store.

Usage
-----
    python scripts/setup_vectorstore.py

The script will:
  1. Check whether chroma_db/ already contains a vector store.
  2. If it does, ask whether to rebuild (answer 'yes' to proceed).
  3. If rebuilding, reset the collection via the Chroma client (no rmtree --
     avoids [WinError 32] when the SQLite file is held open by another process).
  4. Build embeddings for all cases in data/ai_validated_dataset.json and
     persist them to chroma_db/.

Notes
-----
- All output is ASCII-only: Windows' default console code page (cp1252 / cp850)
  cannot render emoji, which would raise UnicodeEncodeError.
- Use Python 3.12+ inside the project virtualenv.
- If you want to abort without rebuilding, answer anything other than 'yes'.
"""
import sys
from pathlib import Path

# Make sure project root is on sys.path so `import config` works when the
# script is run from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import chromadb
import config
from src.chroma_config import CHROMA_SETTINGS
from src.vector_store import vector_store


def _log(tag: str, message: str) -> None:
    print(f"[{tag}] {message}", flush=True)


def _chroma_store_exists() -> bool:
    sqlite_file = config.CHROMA_DIR / "chroma.sqlite3"
    return sqlite_file.exists()


def _reset_collection() -> None:
    _log("INFO", "Resetting existing ChromaDB collection...")
    client = chromadb.PersistentClient(
        path=str(config.CHROMA_DIR),
        settings=CHROMA_SETTINGS,
    )
    client.reset()
    _log("SUCCESS", "Collection reset.")


def main() -> None:
    _log("INFO", f"GP Triage POC - Vector Store Setup")
    _log("INFO", f"Dataset : {config.DATASET_FILE}")
    _log("INFO", f"Chroma  : {config.CHROMA_DIR}")
    _log("INFO", f"Model   : {config.EMBEDDING_MODEL}")

    # Validate dataset
    if not config.DATASET_FILE.exists():
        _log("ERROR", f"Dataset not found at {config.DATASET_FILE}")
        _log("ERROR", "Place ai_validated_dataset.json in the data/ directory and retry.")
        sys.exit(1)

    # Handle existing store
    if _chroma_store_exists():
        _log("INFO", "Existing vector store detected.")
        try:
            answer = input("[PROMPT] Rebuild the vector store? (yes/no): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "no"

        if answer != "yes":
            _log("INFO", "Rebuild cancelled. Existing store retained.")
            sys.exit(0)

        _reset_collection()
    else:
        _log("INFO", "No existing vector store found. Building from scratch.")

    # Build
    _log("INFO", "Loading dataset and generating embeddings (this may take several minutes)...")
    try:
        vector_store.initialize_from_json(str(config.DATASET_FILE))
    except Exception as exc:
        _log("ERROR", f"Failed to build vector store: {exc}")
        sys.exit(1)

    _log("SUCCESS", "Vector store built successfully.")
    _log("INFO", f"You can now run: streamlit run app.py")


if __name__ == "__main__":
    main()
