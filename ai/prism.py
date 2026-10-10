"""Block Convey PRISM tracing for every Nicrron call.

Reads PRISMTRACE_API_KEY / PRISMTRACE_PROJECT_ID / PRISMTRACE_HOST. Without them every function is a
no-op, so the app runs the same with or without PRISM. Nothing here ever raises into the quote path,
and image bytes are never sent: image parts become "[image]".
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
from typing import Any, Iterator

log = logging.getLogger(__name__)

DEFAULT_HOST = "https://prism-api-prod.up.railway.app"
AGENT_ID = "quotepilot-nicrron"
AGENT_NAME = "QuotePilot Nicrron Gateway"
MAX_CHARS = 20_000

_client: Any = None
_lock = threading.Lock()


def _env() -> tuple[str, str, str]:
    return (os.getenv("PRISMTRACE_API_KEY", "").strip(), os.getenv("PRISMTRACE_PROJECT_ID", "").strip(),
            (os.getenv("PRISMTRACE_HOST", "").strip() or DEFAULT_HOST).rstrip("/"))


def configured() -> bool:
    key, project, _ = _env()
    return bool(key and project)


def _get_client():
    global _client
    if not configured():
        return None
    with _lock:
        if _client is None:
            try:
                from prismtrace import PRISMtrace
                key, project, host = _env()
                _client = PRISMtrace(api_key=key, host=host, project_id=project)
            except Exception as exc:  # SDK missing or bad config: tracing off, app unaffected
                log.warning("PRISM disabled: %s", exc)
                return None
        return _client


def status() -> dict:
    _, project, host = _env()
    return {"enabled": configured(), "provider": "Block Convey PRISM", "host": host if configured() else None,
            "project_id": project or None, "agent_id": AGENT_ID}


def current_session() -> str | None:
    try:
        from prismtrace import current_session as cur
        return cur()
    except Exception:
        return None


@contextlib.contextmanager
def session(session_id: str) -> Iterator[str | None]:
    """Groups every model call inside into one PRISM trajectory (one RFQ = one session)."""
    if not configured():
        yield None
        return
    try:
        from prismtrace import session as prism_session
        cm = prism_session(session_id)
    except Exception:
        yield None
        return
    with cm as sid:
        yield sid


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text", "")))
            elif isinstance(p, dict) and p.get("type") in ("image_url", "image", "input_image"):
                parts.append("[image]")
            else:
                parts.append(str(p) if not isinstance(p, dict) else "[part]")
        return "\n".join(parts)
    return "" if content is None else str(content)


def _flatten(messages: list[dict]) -> list[dict]:
    return [{"role": m.get("role", "user"), "content": _text(m.get("content"))[:MAX_CHARS]} for m in messages or []]


def trace_llm(model: str, messages: list[dict], output: str, latency_ms: int, session_id: str | None = None,
              purpose: str | None = None, error: str | None = None, usage: dict | None = None) -> None:
    """Send one completion to PRISM. Never raises."""
    client = _get_client()
    if client is None:
        return
    try:
        sid = session_id or current_session()   # read on the caller thread, before the SDK's background POST
        meta = {"purpose": purpose or "completion", "gateway": "Nicrron", "status": "error" if error else "ok"}
        if error:
            meta["error"] = str(error)[:1000]
        usage = usage or {}
        client.trace_llm(model=model or "unknown", input_messages=_flatten(messages),
                         output=(output or (f"[error] {error}" if error else ""))[:MAX_CHARS],
                         latency_ms=int(latency_ms or 0),
                         token_count_input=int(usage.get("prompt_tokens") or 0),
                         token_count_output=int(usage.get("completion_tokens") or 0),
                         agent_id=AGENT_ID, agent_name=AGENT_NAME, session_id=sid, metadata=meta)
    except Exception as exc:
        log.warning("PRISM trace failed: %s", exc)


def flush(timeout: float = 2.0) -> None:
    client = _client
    if client is None:
        return
    try:
        client.flush(timeout=timeout)
    except Exception as exc:
        log.warning("PRISM flush failed: %s", exc)
