"""
Explicit HTTPX client factory for LangChain OpenAI integrations.

LangChain's OpenAIEmbeddings and ChatOpenAI forward a legacy `proxies=` kwarg
when building default HTTP clients. httpx >= 0.28 removed that kwarg, causing:

    Client.__init__() got an unexpected keyword argument 'proxies'

The fix: create the httpx clients ourselves and inject them. LangChain then
skips building its own clients, so the `proxies` kwarg is never forwarded.

Usage
-----
    http_client, async_http_client = create_openai_http_clients()
    OpenAIEmbeddings(..., http_client=http_client, http_async_client=async_http_client)
    ChatOpenAI(...,       http_client=http_client, http_async_client=async_http_client)
"""
import atexit
import httpx

_sync_client: httpx.Client | None = None
_async_client: httpx.AsyncClient | None = None


def _cleanup() -> None:
    global _sync_client, _async_client
    if _sync_client is not None:
        try:
            _sync_client.close()
        except Exception:
            pass
    if _async_client is not None:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if not loop.is_closed() and loop.is_running():
                loop.create_task(_async_client.aclose())
            else:
                loop.run_until_complete(_async_client.aclose())
        except Exception:
            pass


def create_openai_http_clients() -> tuple[httpx.Client, httpx.AsyncClient]:
    """Return the process-level sync and async httpx clients, creating them on first call."""
    global _sync_client, _async_client
    if _sync_client is None:
        _sync_client = httpx.Client()
        _async_client = httpx.AsyncClient()
        atexit.register(_cleanup)
    return _sync_client, _async_client
