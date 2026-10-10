"""Real Nicrron gateway calls. No fake responses or rules-only runtime fallback."""
from __future__ import annotations
import base64
import json
import os
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError
from ai.engine import extract_rule_line

DEFAULT_BASE_URL = "https://api.nicrron.ai/v1"
DEFAULT_MODEL = "nicrron/auto"
DEFAULT_VISION_MODEL = "anthropic/claude-haiku-4-5"

SYSTEM_PROMPT = """You extract line items from an industrial buyer RFQ.
Return a valid JSON object with one top-level key: "lines" (an array).
Each line MUST have:
- raw_text: an EXACT contiguous substring from the user's original text (verbatim)
- material: stainless_steel, carbon_steel or null
- form: sheet, plate or null
- grade: 304, 316, 316L, A36, etc., or null
- thickness_in, width_in, length_in: number in inches or null
- quantity: integer or null
- standard_required: only a standard explicitly requested by the buyer, e.g. ASTM A240, or null
- required_certificates: array, use MTR only when buyer explicitly mentions mill cert/test report
- country_of_origin_required: boolean, true only when buyer explicitly requests it
- evidence: object mapping non-null extracted fields to EXACT verbatim substrings that support them

Important safeguards:
Never fill a missing value from your own assumptions or from typical industry specifications.
'4x8' following sheet dimensions commonly means feet; normalize to 48x96 inches only with clear context.
'16ga' has material-specific thickness; if unsure, return thickness_in=null.
Never invent ASTM standards, quotes, prices, supplier inventory, certificates or customer names.
Never invent extra line items. Split each separately requested product into its own line.
Missing values must be JSON null. Do not include markdown fences, commentary or trailing commas.
"""

IMAGE_TRANSCRIBE_PROMPT = """Transcribe all readable text from this industrial RFQ image or screenshot.
Return ONLY the plain text that is visibly present. Preserve line breaks where helpful.
Do not invent, correct, or complete missing text. Do not add commentary or markdown.
If there is no readable text, reply with exactly: EMPTY
"""


class ModelLine(BaseModel):
    raw_text: str = Field(min_length=1)
    material: str | None = None
    form: str | None = None
    grade: str | None = None
    thickness_in: float | None = None
    width_in: float | None = None
    length_in: float | None = None
    quantity: int | None = None
    standard_required: str | None = None
    required_certificates: list[str] = Field(default_factory=list)
    country_of_origin_required: bool = False
    evidence: dict[str, str] = Field(default_factory=dict)

class Extraction(BaseModel):
    lines: list[ModelLine] = Field(min_length=1, max_length=60)


class GatewayConfigurationError(Exception):
    pass


class GatewayResponseError(Exception):
    pass


def config() -> dict:
    return {
        "configured": bool(os.getenv("NICRRON_API_KEY", "").strip()),
        "base_url": os.getenv("NICRRON_BASE_URL", DEFAULT_BASE_URL),
        "model": os.getenv("NICRRON_MODEL", DEFAULT_MODEL),
        "vision_model": os.getenv("NICRRON_VISION_MODEL", DEFAULT_VISION_MODEL),
    }


def gateway_auth() -> tuple[str,str]:
    api_key = os.getenv("NICRRON_API_KEY", "").strip()
    if not api_key:
        raise GatewayConfigurationError("NICRRON_API_KEY is missing. Put it in your local .env file and restart the server.")
    base = os.getenv("NICRRON_BASE_URL", DEFAULT_BASE_URL).rstrip('/')
    if not base.startswith('https://') and not (os.getenv('ALLOW_INSECURE_GATEWAY')=='true' and base.startswith('http://127.0.0.1')):
        raise GatewayConfigurationError('Gateway base URL must use HTTPS (except explicitly authorized localhost tests)')
    return base, api_key


def sniff_image_mime(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(raw) >= 3 and raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a"):
        return "image/gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _completion(
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 2200,
    model: str | None = None,
) -> tuple[str, str, int]:
    base, api_key = gateway_auth()
    resolved_model = model or os.getenv("NICRRON_MODEL", DEFAULT_MODEL)
    start = time.monotonic()
    try:
        # This executes a REAL HTTPS request to the Nicrron API gateway.
        # No local stub, mock response, or fallback in runtime code.
        with httpx.Client(timeout=float(os.getenv("NICRRON_TIMEOUT_SECONDS", "40"))) as client:
            response = client.post(
                base + "/chat/completions",
                headers={"Authorization": "Bearer " + api_key,
                         "Content-Type": "application/json"},
                json={"model": resolved_model, "messages": messages, "max_tokens": max_tokens},
            )
            if response.status_code >= 400:
                raise GatewayResponseError(
                    "Nicrron HTTP " + str(response.status_code) + ": " + response.text[:260]
                )
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GatewayResponseError("Nicrron network or response failure: " + str(exc)[:260]) from exc
    elapsed = round((time.monotonic() - start) * 1000)
    try:
        content = payload['choices'][0]['message']['content']
        real_model = payload.get('model') or resolved_model
    except (KeyError, IndexError, TypeError) as exc:
        raise GatewayResponseError("Gateway response missing choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise GatewayResponseError("Gateway returned no assistant text")
    return content, real_model, elapsed


def transcribe_image(image_bytes: bytes, mime: str) -> tuple[str, dict[str, Any]]:
    """Send image bytes to a vision-capable Nicrron model; return plain-text transcript + meta."""
    if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        raise GatewayResponseError(f"Unsupported image MIME type for vision: {mime}")
    vision_model = os.getenv("NICRRON_VISION_MODEL", DEFAULT_VISION_MODEL)
    data_url = f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")
    content, model, latency_ms = _completion(
        [
            {"role": "system", "content": IMAGE_TRANSCRIBE_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe the RFQ text in this image."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        max_tokens=2000,
        model=vision_model,
    )
    text = content.strip()
    if text.upper() == "EMPTY" or not text:
        raise GatewayResponseError("Vision model found no readable text in the image")
    return text, {
        "vision_model": model,
        "vision_latency_ms": latency_ms,
        "source": "image_transcript",
    }

def test_connection() -> dict:
    response, model, latency = _completion([
        {"role":"system", "content":"Reply only with OK."},
        {"role":"user", "content":"Ping for an industrial RFQ quoting application."}
    ], max_tokens=25)
    return {"connected": True, "model": model, "latency_ms": latency, "model_reply": response[:200],
            "provider": "Nicrron", "gateway_call": "live"}


def _parse_json(raw: str) -> dict[str, Any]:
    clean = raw.strip()
    if clean.startswith('```'):
        clean = re.sub(r'^```(?:json)?\s*', '', clean, flags=re.I)
        clean = re.sub(r'\s*```$', '', clean)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise GatewayResponseError(f"Model did not return valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise GatewayResponseError("Model output must be a JSON object")
    return payload


def _evidenced(raw: str, field: str, value: Any, evidence: dict[str,str]) -> bool:
    """Do not trust inferred values unless supported by verbatim text."""
    proof = evidence.get(field)
    if not isinstance(proof,str) or not proof.strip() or proof.lower() not in raw.lower():
        return False
    if field in ('grade','standard_required') and str(value).replace(' ','').lower() not in proof.replace(' ','').lower():
        return False
    if field == 'quantity' and str(value) not in proof:
        return False
    return True


def _squash(s: str) -> str:
    return ' '.join(s.split())


def _tokens(s: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-/#]*", s.upper())


def extract_live(text: str) -> tuple[list[dict], dict]:
    raw_json, model, latency_ms = _completion([
        {"role":"system", "content":SYSTEM_PROMPT},
        {"role":"user", "content":text},
    ], max_tokens=int(os.getenv("NICRRON_EXTRACT_MAX_TOKENS", "8000")))   # 2800 ran out on 8-line RFQs (finish_reason=length)
    try:
        result = Extraction.model_validate(_parse_json(raw_json))
    except (ValidationError, ValueError) as exc:
        raise GatewayResponseError("Model output failed schema validation: " + str(exc)[:220]) from exc

    lines: list[dict] = []
    source_squashed = _squash(text)
    source_tokens = set(_tokens(text))
    for idx, proposed in enumerate(result.lines, start=1):
        raw = proposed.raw_text.strip()
        # PDF text layers break table cells across lines/columns, so the model's joined line is often not one
        # exact substring. Accept it when it matches ignoring whitespace, or when every word in it appears in
        # the source (the model only re-joined words, it added none).
        if raw in text or _squash(raw) in source_squashed:
            grounding = 'exact'
        elif _tokens(raw) and set(_tokens(raw)) <= source_tokens:
            grounding = 'words_in_source'
        else:
            # Can't verify this line: keep it visible for review, but trust nothing extracted from it.
            item = extract_rule_line(raw, idx)
            for f in ('material', 'form', 'grade', 'thickness_in', 'width_in', 'length_in', 'quantity', 'standard_required'):
                item[f] = None
            item['extraction_source'] = 'nicrron_live_unverified'
            item['grounding'] = 'not_found_in_source'
            lines.append(item)
            continue
        # Start with deterministic extraction; accept LLM supplements ONLY if explicitly evidenced.
        item = extract_rule_line(raw, idx)
        item['grounding'] = grounding
        candidate = proposed.model_dump()
        for field in ('material', 'form', 'grade', 'thickness_in', 'width_in', 'length_in',
                      'quantity', 'standard_required', 'country_of_origin_required'):
            value = candidate[field]
            if item.get(field) is not None or value is None:
                continue
            if not _evidenced(raw, field, value, proposed.evidence):
                continue
            if field in ('thickness_in', 'width_in', 'length_in') and (not isinstance(value,(float,int)) or value <= 0):
                continue
            if field == 'quantity' and value <= 0:
                continue
            item[field] = value
        # Certificate flags must be explicitly grounded: deterministic detection is authoritative.
        item['extraction_source'] = 'nicrron_live_plus_validation'
        lines.append(item)

    return lines, {
        "mode":"live_gateway", "gateway":"Nicrron", "model":model,
        "latency_ms":latency_ms, "validation":"source-grounded + deterministic"
    }
