"""
Shared ChromaDB settings.

Import CHROMA_SETTINGS everywhere a chromadb client is instantiated so that
multiple processes (the setup script and the Streamlit app) always agree on
the same configuration. Mismatched settings cause chromadb to raise
"instance already exists with different settings".
"""
from chromadb.config import Settings

CHROMA_SETTINGS = Settings(
    allow_reset=True,
    anonymized_telemetry=False,
)
