"""OpenAI-compatible providers: Nicrron (the sponsor gateway) and OpenAI itself.

Nicrron is the OpenAI SDK pointed at https://api.nicrron.ai/v1 with NICRRON_API_KEY.
"""
from __future__ import annotations

import base64
import json
import re
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
        # Gateways route to many models and some ignore response_format (Nicrron's Claude routes answer in
        # Markdown), so the schema also goes in the instructions and the reply is parsed tolerantly.
        system = (f"{system}\n\nReply with ONLY one JSON object that matches this JSON Schema. No prose, no Markdown, "
                  f"no code fences.\n{json.dumps(schema)}")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        t0 = time.monotonic()
        usage_in = usage_out = 0
        for attempt in range(2):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model, max_tokens=max_tokens, messages=messages,
                    response_format={"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": True}},
                )
            except openai.AuthenticationError as e:
                raise ProviderUnavailable(f"{self.name} rejected the API key") from e
            except openai.APIConnectionError as e:
                raise ProviderUnavailable(f"Could not reach {self.name}") from e
            except openai.APIStatusError as e:
                raise ProviderUnavailable(f"{self.name} error {e.status_code}") from e
            text = resp.choices[0].message.content or ""
            usage_in += getattr(resp.usage, "prompt_tokens", 0) or 0
            usage_out += getattr(resp.usage, "completion_tokens", 0) or 0
            data = parse_json_reply(text)
            if data is not None:
                return LLMResult(data=data, model=resp.model or self.model, latency_ms=int((time.monotonic() - t0) * 1000),
                                 input_tokens=usage_in, output_tokens=usage_out, raw_text=text, meta={"attempts": attempt + 1})
            messages = messages + [{"role": "assistant", "content": text},
                                   {"role": "user", "content": "That was not JSON. Reply again with only the JSON object."}]
        raise ProviderUnavailable(f"{self.name} returned invalid JSON twice")


def parse_json_reply(text: str) -> dict | None:
    """The reply as JSON; else the body of a ```json fence; else the span from the first { to the last }."""
    candidates = [text.strip()]
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        candidates.append(m[1].strip())
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{"): text.rindex("}") + 1])
    for c in candidates:
        try:
            v = json.loads(c)
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            continue
    return None


def nicrron() -> OpenAICompatProvider:
    return OpenAICompatProvider(
        "nicrron", os.environ.get("NICRRON_BASE_URL", "https://api.nicrron.ai/v1"),
        "NICRRON_API_KEY", os.environ.get("NICRRON_MODEL", "anthropic/claude-sonnet-5"),
    )


def openai_direct() -> OpenAICompatProvider:
    return OpenAICompatProvider("openai", None, "OPENAI_API_KEY", os.environ.get("OPENAI_MODEL", "gpt-5.5"))
