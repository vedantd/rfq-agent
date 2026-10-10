"""LLM provider interface. Every provider takes the same inputs and returns plain dicts,
so swapping Claude for Nicrron (or anything else) is one env var: LLM_PROVIDER."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Attachment:
    data: bytes
    media_type: str  # image/png, image/jpeg, image/webp, image/gif, application/pdf
    name: str = ""


@dataclass
class LLMResult:
    data: dict
    model: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw_text: str = ""
    meta: dict = field(default_factory=dict)


class ProviderUnavailable(RuntimeError):
    """Raised when the configured provider cannot run (no key, rules-only mode, unsupported input)."""


class LLMProvider:
    name = "base"
    model = ""
    supports_images = False
    supports_pdf = False

    def complete_json(self, *, system: str, prompt: str, schema: dict, schema_name: str,
                      attachments: list[Attachment] | None = None, max_tokens: int = 16000) -> LLMResult:
        raise NotImplementedError


class RulesOnlyProvider(LLMProvider):
    """No model at all. Callers fall back to the deterministic parser and template text."""
    name = "rules"
    model = "rules-only"

    def complete_json(self, **kwargs) -> LLMResult:
        raise ProviderUnavailable("LLM_PROVIDER=rules: no model configured")
