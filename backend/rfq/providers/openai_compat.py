"""OpenAI-compatible providers: Nicrron (the sponsor gateway) and OpenAI itself.

Nicrron is the OpenAI SDK pointed at https://api.nicrron.ai/v1 with NICRRON_API_KEY.
"""
from __future__ import annotations

import base64
import json
import os
import time

import openai

from .base import LLMProvider, LLMResult, ProviderUnavailable


class OpenAICompatProvider(LLMProvider):
    supports_images = True
    supports_pdf = False  # PDFs are sent as text, or as page images when they have no text layer

    def __init__(self, name: str, base_url: str | None, key_env: str, model: str):
        key = os.environ.get(key_env)
        if not key:
            raise ProviderUnavailable(f"{key_env} is not set")
        self.name = name
        self.model = model
        self.client = openai.OpenAI(api_key=key, base_url=base_url)

    def complete_json(self, *, system, prompt, schema, schema_name, attachments=None, max_tokens=16000):
        content: list[dict] = [{"type": "text", "text": prompt}]
        for a in attachments or []:
            if a.media_type.startswith("image/"):
                b64 = base64.standard_b64encode(a.data).decode("ascii")
                content.append({"type": "image_url", "image_url": {"url": f"data:{a.media_type};base64,{b64}"}})
        t0 = time.monotonic()
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
                response_format={"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": True}},
            )
        except openai.AuthenticationError as e:
            raise ProviderUnavailable(f"{self.name} rejected the API key") from e
        except openai.APIConnectionError as e:
            raise ProviderUnavailable(f"Could not reach {self.name}") from e
        latency = int((time.monotonic() - t0) * 1000)
        text = resp.choices[0].message.content or ""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProviderUnavailable(f"{self.name} returned invalid JSON") from e
        usage = resp.usage
        return LLMResult(
            data=data, model=resp.model or self.model, latency_ms=latency,
            input_tokens=getattr(usage, "prompt_tokens", None), output_tokens=getattr(usage, "completion_tokens", None),
            raw_text=text,
        )


def nicrron() -> OpenAICompatProvider:
    return OpenAICompatProvider(
        "nicrron", os.environ.get("NICRRON_BASE_URL", "https://api.nicrron.ai/v1"),
        "NICRRON_API_KEY", os.environ.get("NICRRON_MODEL", "anthropic/claude-sonnet-5"),
    )


def openai_direct() -> OpenAICompatProvider:
    return OpenAICompatProvider("openai", None, "OPENAI_API_KEY", os.environ.get("OPENAI_MODEL", "gpt-5.5"))
