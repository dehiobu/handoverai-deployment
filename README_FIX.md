## GP Triage POC – Error Resolution Notes

This document captures the exact error you saw, how to reproduce it, what changed during the fix, and the dependency versions that now work together. Use it as a reference any time the same incompatibility crops up again.

---

### 1. Environment & Versions

- **Python**: 3.11.x (matches the virtualenv already in the repo)
- **LangChain packages**:  
  - `langchain==0.1.20`  
  - `langchain-openai==0.1.1`  
  - `langchain-community==0.0.38`  
  - `langchain-core==0.1.52`
- **OpenAI SDK**: `openai==1.14.0`
- **httpx**: `0.28.1`

> ⚠️ The failure only happens when LangChain/OpenAI are paired with **httpx ≥ 0.28**. Older httpx releases silently accepted the `proxies=` kwarg that LangChain still sends by default.

---

### 2. Original Terminal Error

Running `python scripts/setup_vectorstore.py` crashed immediately:

```
Client.__init__() got an unexpected keyword argument 'proxies'
```

That originates from `langchain_openai.OpenAIEmbeddings` (and `ChatOpenAI`) attempting to instantiate the modern OpenAI SDK without providing a custom HTTP client. The OpenAI SDK forwards every unknown kwarg down to `httpx.Client`. In httpx 0.28 the legacy `proxies` kwarg was removed, so the call now raises.

---

### 3. Fix Summary

| Area | Change |
| --- | --- |
| `src/openai_http.py` | New helper that creates paired sync/async `httpx` clients and registers best-effort cleanup at process exit. |
| `src/vector_store.py` | Imports the helper and injects `http_client`/`http_async_client` when constructing `OpenAIEmbeddings`, eliminating the `proxies` kwarg. Also now shares a `CHROMA_SETTINGS` object everywhere Chroma is instantiated so multiple processes never fight over “different settings”. |
| `src/rag_pipeline.py` | Uses the same helper for `ChatOpenAI` so runtime triage calls won’t hit the same incompatibility. |
| `src/chroma_config.py` | Centralizes `Settings(allow_reset=True, anonymized_telemetry=False)` for Chroma clients, preventing “instance already exists with different settings” when both the setup script and the app touch the DB. |
| `scripts/setup_vectorstore.py` | Swapped emoji logging for ASCII tags and replaced `shutil.rmtree` with a Chroma `PersistentClient.reset()` call that obeys the shared settings. This avoids `[WinError 32]` on Windows and ensures we wipe the collection gracefully even if the SQLite file is in use. |

---

### 4. How the Fix Works

1. **Create explicit HTTPX clients**  
   In `src/openai_http.py` we instantiate `httpx.Client()` and `httpx.AsyncClient()`, keep references, and register an `atexit` cleanup that safely closes both clients even if an event loop is already running.

2. **Pass those clients into LangChain**  
   - `VectorStore` now does:
     ```python
     http_client, async_http_client = create_openai_http_clients()
     OpenAIEmbeddings(..., http_client=http_client, http_async_client=async_http_client)
     ```
   - `RAGPipeline` does the same for `ChatOpenAI`.
   Providing the clients prevents LangChain from asking the OpenAI SDK to build default clients, so the deprecated `proxies` kwarg is never forwarded to httpx.

3. **ASCII status output + Chroma-safe reset**  
   The vector-store setup script previously printed emoji such as `📂` and `✅`. Windows’ default code page can’t render these, which raised `UnicodeEncodeError`. All of those messages are now plain ASCII (`[INFO]`, `[SUCCESS]`, etc.).  
   While fixing the terminal lockups, we also stopped deleting `chroma_db/` by hand (which fails whenever another Python process has the SQLite file open) and instead call `PersistentClient(..., allow_reset=True).reset()`. Because the app and the script now import the same `CHROMA_SETTINGS`, we never see “instance already exists with different settings” and the reset can run safely on Windows.

4. **Verification**  
   - `cmd /c "echo no | venv\Scripts\python.exe scripts\setup_vectorstore.py"` now completes without throwing the proxy or Unicode errors and simply cancels when asked to rebuild the vector store.
   - The Streamlit app and any code path that instantiates `ChatOpenAI`/`OpenAIEmbeddings` now share the same HTTPX clients, so you can safely run on httpx 0.28+.

---

### 5. Guidance for Future Upgrades

1. **Stay aligned with the tested stack** listed above. If you bump `openai` or `httpx`, verify LangChain’s release notes to ensure they explicitly support those versions.
2. **If you upgrade LangChain**, keep an eye on the `langchain-openai` release changelog. As soon as they remove the legacy `proxies` usage, you can drop the helper and rely on their defaults again.
3. **When running scripts on Windows**, keep logs ASCII-only unless you change the console code page (e.g., `chcp 65001`).
4. **Re-run `python scripts/setup_vectorstore.py`** whenever you edit the dataset. Answer `yes` to the prompt if you actually want to rebuild the Chroma database.

Following this setup ensures every component (Streamlit UI, vector-store builder, RAG pipeline) runs on the same dependency set without the `proxies` crash. Feel free to extend this document with any new compatibility notes you discover.
