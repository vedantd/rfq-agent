"""Claude via the official Anthropic SDK."""
from __future__ import annotations

import base64
import json
import os
import time

import anthropic

from .base import Attachment, LLMProvider, LLMResult, ProviderUnavailable


class ClaudeProvider(LLMProvider):
    name = "claude"
    supports_images = True
    supports_pdf = True

    def __init__(self):
        self.model = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
        self.effort = os.environ.get("CLAUDE_EFFORT", "medium")
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ant profile

    def complete_json(self, *, system, prompt, schema, schema_name, attachments=None, max_tokens=16000):
        content: list[dict] = []
        for a in attachments or []:
            b64 = base64.standard_b64encode(a.data).decode("ascii")
            if a.media_type == "application/pdf":
                content.append({"type": "document", "source": {"type": "base64", "media_type": a.media_type, "data": b64}})
            else:
                content.append({"type": "image", "source": {"type": "base64", "media_type": a.media_type, "data": b64}})
        content.append({"type": "text", "text": prompt})

        t0 = time.monotonic()
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise ProviderUnavailable("Claude rejected the credentials; check ANTHROPIC_API_KEY") from e
        except anthropic.APIConnectionError as e:
            raise ProviderUnavailable("Could not reach the Claude API") from e
        latency = int((time.monotonic() - t0) * 1000)

        if response.stop_reason == "refusal":
            raise ProviderUnavailable("Claude declined this request")
        if response.stop_reason == "max_tokens":
            raise ProviderUnavailable("Claude's answer was cut off (max_tokens); the RFQ may be too long")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return LLMResult(
            data=json.loads(text),
            model=response.model,
            latency_ms=latency,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            raw_text=text,
            meta={"request_id": response._request_id},
        )
