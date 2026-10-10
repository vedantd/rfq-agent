"""Agent run tracing for Block Convey PRISM.

Every RFQ run becomes one PRISM session (session_id = rfq id) with:
  - one trace per LLM call (POST /api/traces), and
  - one agent-run trace plus its step spans (POST /api/spans/ingest).
Without PRISMTRACE_* env vars, the same payloads go to var/traces.jsonl so nothing is lost
and GET /v1/traces can show them in the demo.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx

from .refdata import RUNTIME_DIR

TRACE_FILE = RUNTIME_DIR / "traces.jsonl"
AGENT_ID = "rfq-to-quote"
_lock = threading.Lock()
_last_error: str | None = None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def prism_config() -> dict | None:
    host = os.environ.get("PRISMTRACE_HOST", "https://prism.blockconvey.com")
    key, project = os.environ.get("PRISMTRACE_API_KEY"), os.environ.get("PRISMTRACE_PROJECT_ID")
    if not key or not project:
        return None
    return {"host": host.rstrip("/"), "key": key, "project": project}


def prism_status() -> dict:
    cfg = prism_config()
    return {"enabled": cfg is not None, "host": cfg["host"] if cfg else None, "last_error": _last_error}


def _local(kind: str, payload: dict):
    with _lock:
        with open(TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "at": _iso(time.time()), **payload}, default=str) + "\n")


def _send(path: str, payload: dict):
    global _last_error
    cfg = prism_config()
    if not cfg:
        return
    def go():
        global _last_error
        try:
            r = httpx.post(cfg["host"] + path, headers={"X-PRISMtrace-Key": cfg["key"]},
                           json={"project_id": cfg["project"], **payload}, timeout=10)
            if r.status_code >= 400:
                _last_error = f"{path}: HTTP {r.status_code} {r.text[:200]}"
        except httpx.HTTPError as e:
            _last_error = f"{path}: {e}"
    threading.Thread(target=go, daemon=True).start()


class Run:
    """One agent run (ingest -> parse -> match -> price -> compliance -> clarify) for one RFQ."""

    def __init__(self, rfq_id: str, name: str):
        self.rfq_id = rfq_id
        self.name = name
        self.trace_id = str(uuid.uuid4())
        self.t0 = time.time()
        self.spans: list[dict] = []

    @contextmanager
    def span(self, name: str, span_type: str = "chain", **meta):
        start = time.time()
        rec = {"name": name, "span_type": span_type, "start_time": _iso(start), "status": "ok", "metadata": meta}
        try:
            yield rec["metadata"]
        except Exception as e:
            rec["status"] = "error"
            rec["metadata"]["error"] = str(e)
            raise
        finally:
            end = time.time()
            rec["end_time"] = _iso(end)
            rec["duration_ms"] = int((end - start) * 1000)
            self.spans.append(rec)

    def llm_call(self, *, purpose: str, provider: str, model: str, prompt: str, output: str,
                 latency_ms: int, input_tokens=None, output_tokens=None, error: str | None = None):
        payload = {
            "model": model,
            "input_messages": [{"role": "user", "content": prompt[:20000]}],
            "output_message": output[:20000] if output else (f"ERROR: {error}" if error else ""),
            "latency_ms": latency_ms,
            "session_id": self.rfq_id,
            "agent_id": AGENT_ID,
            "agent_name": "RFQ to Quote",
            "token_count_input": input_tokens,
            "token_count_output": output_tokens,
            "metadata": {"purpose": purpose, "provider": provider, "run_trace_id": self.trace_id, "error": error},
        }
        self.spans.append({"name": f"llm:{purpose}", "span_type": "llm", "start_time": _iso(time.time() - latency_ms / 1000),
                           "end_time": _iso(time.time()), "status": "error" if error else "ok", "model": model,
                           "metadata": {"provider": provider}})
        _local("llm_call", {"rfq_id": self.rfq_id, **payload})
        _send("/api/traces", payload)

    def finish(self, *, input_text: str, output_summary: str, metadata: dict):
        latency = int((time.time() - self.t0) * 1000)
        trace = {
            "trace_id": self.trace_id,
            "model": "rfq-agent-pipeline",
            "input_messages": [{"role": "user", "content": input_text[:20000]}],
            "output_message": output_summary,
            "latency_ms": latency,
            "session_id": self.rfq_id,
            "agent_id": AGENT_ID,
            "agent_name": "RFQ to Quote",
            "metadata": {"run": self.name, **metadata},
        }
        _local("agent_run", {"rfq_id": self.rfq_id, **trace, "spans": self.spans})
        _send("/api/traces", trace)
        _send("/api/spans/ingest", {"trace_id": self.trace_id, "session_id": self.rfq_id, "spans": self.spans,
                                    "metadata": {"run": self.name}})
        return {"trace_id": self.trace_id, "latency_ms": latency}


def read_local(rfq_id: str | None = None, limit: int = 200) -> list[dict]:
    if not TRACE_FILE.exists():
        return []
    out = []
    with open(TRACE_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rfq_id is None or rec.get("rfq_id") == rfq_id:
                out.append(rec)
    return out[-limit:]
