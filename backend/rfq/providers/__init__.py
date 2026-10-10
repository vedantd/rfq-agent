"""Pick the LLM provider from the environment.

LLM_PROVIDER = claude | nicrron | openai | rules
Default: claude when ANTHROPIC_API_KEY is set, otherwise rules (no model, deterministic only).
"""
from __future__ import annotations

import os

from .base import Attachment, LLMProvider, LLMResult, ProviderUnavailable, RulesOnlyProvider

_cached: LLMProvider | None = None
_cached_name: str | None = None
_error: str | None = None


def configured_name() -> str:
    name = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if not name:
        name = "claude" if os.environ.get("ANTHROPIC_API_KEY") else "rules"
    return name


def get_provider() -> LLMProvider:
    """Return the configured provider, or RulesOnlyProvider if it cannot start (reason in provider_status())."""
    global _cached, _cached_name, _error
    name = configured_name()
    if _cached is not None and _cached_name == name:
        return _cached
    _error = None
    try:
        if name == "claude":
            from .claude import ClaudeProvider
            p: LLMProvider = ClaudeProvider()
        elif name == "nicrron":
            from .openai_compat import nicrron
            p = nicrron()
        elif name == "openai":
            from .openai_compat import openai_direct
            p = openai_direct()
        else:
            p = RulesOnlyProvider()
    except ProviderUnavailable as e:
        _error = str(e)
        p = RulesOnlyProvider()
    _cached, _cached_name = p, name
    return p


def provider_status() -> dict:
    p = get_provider()
    return {"configured": configured_name(), "active": p.name, "model": p.model, "error": _error}


__all__ = ["Attachment", "LLMProvider", "LLMResult", "ProviderUnavailable", "get_provider", "provider_status"]
