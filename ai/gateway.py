"""Real Nicrron gateway calls. No fake responses or rules-only runtime fallback."""
from __future__ import annotations
import base64
import io
import json
import os
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator
from ai.engine import extract_rule_line
from ai import prism

DEFAULT_BASE_URL = "https://api.nicrron.ai/v1"
# nicrron/auto can route to slow reasoning models; fastest keeps text RFQs snappy.
DEFAULT_MODEL = "nicrron/fastest"
# Fast/cheap vision default — one multimodal call must finish the image RFQ path.
DEFAULT_VISION_MODEL = "openai/gpt-4o-mini"
DEFAULT_VISION_TIMEOUT_SECONDS = 25
DEFAULT_VISION_MAX_EDGE = 1280
DEFAULT_VISION_JPEG_QUALITY = 70

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

IMAGE_EXTRACT_PROMPT = """You read an industrial RFQ image (email screenshot, BOM table, photo of notes, or forwarded thread).
Return ONE valid JSON object with keys:
- source_text: plain text of readable content needed to ground line items (keep material lines verbatim; you may omit pure chrome/noise)
- lines: array of metal sheet/plate RFQ line items only

Each lines[] entry MUST have the same fields as a text RFQ extract:
raw_text, material, form, grade, thickness_in, width_in, length_in, quantity,
standard_required, required_certificates, country_of_origin_required, evidence

Rules:
- raw_text MUST be an EXACT contiguous substring of source_text.
- ONLY extract stainless/carbon steel sheet or plate purchase lines.
- IGNORE greetings, signatures, phone numbers, PO numbers, addresses, ASAP pleas,
  email chrome, rev labels, drywall/hardware, coffee notes, unsubscribe footers, and admin rows.
- Never invent missing grades/sizes. Use JSON null when not visible.
- If no metal sheet/plate lines are visible, return {"source_text":"","lines":[]}.
- No markdown fences or commentary.
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

    @field_validator('required_certificates', mode='before')
    @classmethod
    def _certs(cls, v):
        if v is None:
            return []
        if isinstance(v, bool):
            # Models sometimes answer `true` here. Which certificate is unknown, and certificate
            # flags are decided by the deterministic rule parser from the source text anyway.
            return []
        if isinstance(v, str):
            low = v.lower()
            if 'mtr' in low or 'mill cert' in low or 'mill test' in low:
                return ['MTR']
            return [v] if v.strip() else []
        if isinstance(v, list):
            return [str(x) for x in v if x not in (None, '', False, True)]
        return []

    @field_validator('thickness_in', 'width_in', 'length_in', mode='before')
    @classmethod
    def _number(cls, v):
        # "0.06 in" -> 0.06; anything unreadable becomes null (asked as a clarification, never guessed)
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return v
        m = re.search(r'-?\d*\.?\d+', str(v))
        return float(m.group()) if m else None

    @field_validator('quantity', mode='before')
    @classmethod
    def _qty(cls, v):
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, float):
            return int(v) if v.is_integer() else None
        if isinstance(v, int):
            return v
        m = re.fullmatch(r'\s*(\d+)\s*[A-Za-z. ]*', str(v))   # "24 sheets" -> 24
        return int(m.group(1)) if m else None

    @field_validator('material', 'form', 'grade', 'standard_required', mode='before')
    @classmethod
    def _text(cls, v):
        if v is None or isinstance(v, (bool, list, dict)):
            return None
        return str(v)

    @field_validator('evidence', mode='before')
    @classmethod
    def _evidence(cls, v):
        if not isinstance(v, dict):
            return {}
        return {str(k): str(x) for k, x in v.items() if isinstance(x, (str, int, float)) and not isinstance(x, bool)}

    @field_validator('country_of_origin_required', mode='before')
    @classmethod
    def _coo(cls, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ('true', 'yes', 'y', '1')
        return False

class Extraction(BaseModel):
    lines: list[ModelLine] = Field(min_length=1, max_length=60)


class ImageExtraction(BaseModel):
    source_text: str = Field(min_length=1)
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
        "vision_timeout_seconds": float(os.getenv("NICRRON_VISION_TIMEOUT_SECONDS", str(DEFAULT_VISION_TIMEOUT_SECONDS))),
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


def _prepare_vision_image(image_bytes: bytes, mime: str) -> tuple[bytes, str]:
    """Downscale and JPEG-compress so the multimodal call stays under the latency budget."""
    try:
        from PIL import Image
    except ImportError:
        return image_bytes, mime
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB")
    except Exception as exc:
        raise GatewayResponseError(f"Could not decode image for vision: {type(exc).__name__}") from exc
    max_edge = int(os.getenv("NICRRON_VISION_MAX_EDGE", str(DEFAULT_VISION_MAX_EDGE)))
    w, h = img.size
    scale = min(1.0, max_edge / max(w, h))
    if scale < 1.0:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    quality = int(os.getenv("NICRRON_VISION_JPEG_QUALITY", str(DEFAULT_VISION_JPEG_QUALITY)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue(), "image/jpeg"


def _completion(
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 2200,
    model: str | None = None,
    timeout_seconds: float | None = None,
    purpose: str | None = None,
) -> tuple[str, str, int]:
    base, api_key = gateway_auth()
    resolved_model = model or os.getenv("NICRRON_MODEL", DEFAULT_MODEL)
    timeout = timeout_seconds if timeout_seconds is not None else float(os.getenv("NICRRON_TIMEOUT_SECONDS", "40"))
    start = time.monotonic()

    def _fail(msg: str) -> GatewayResponseError:   # every failed call is traced to PRISM too
        prism.trace_llm(model=resolved_model, messages=messages, output="", purpose=purpose, error=msg,
                        latency_ms=round((time.monotonic() - start) * 1000))
        return GatewayResponseError(msg)

    try:
        # This executes a REAL HTTPS request to the Nicrron API gateway.
        # No local stub, mock response, or fallback in runtime code.
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                base + "/chat/completions",
                headers={"Authorization": "Bearer " + api_key,
                         "Content-Type": "application/json"},
                json={"model": resolved_model, "messages": messages, "max_tokens": max_tokens},
            )
            if response.status_code >= 400:
                raise _fail("Nicrron HTTP " + str(response.status_code) + ": " + response.text[:260])
            payload = response.json()
    except GatewayResponseError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise _fail("Nicrron network or response failure: " + str(exc)[:260]) from exc
    elapsed = round((time.monotonic() - start) * 1000)
    try:
        content = payload['choices'][0]['message']['content']
        real_model = payload.get('model') or resolved_model
    except (KeyError, IndexError, TypeError) as exc:
        raise _fail("Gateway response missing choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise _fail("Gateway returned no assistant text")
    prism.trace_llm(model=real_model, messages=messages, output=content, latency_ms=elapsed, purpose=purpose,
                    usage=payload.get("usage") if isinstance(payload, dict) else None)
    return content, real_model, elapsed

def test_connection() -> dict:
    with prism.session("gateway-test"):
        response, model, latency = _completion([
            {"role":"system", "content":"Reply only with OK."},
            {"role":"user", "content":"Ping for an industrial RFQ quoting application."}
        ], max_tokens=25, purpose="gateway_test")
        prism.flush()
    return {"prism": prism.status(), "connected": True, "model": model, "latency_ms": latency, "model_reply": response[:200],
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


def _grounded_lines(result: Extraction, source_text: str) -> list[dict]:
    lines: list[dict] = []
    source_squashed = _squash(source_text)
    source_tokens = set(_tokens(source_text))
    for idx, proposed in enumerate(result.lines, start=1):
        raw = proposed.raw_text.strip()
        # PDF text layers break table cells across lines/columns, so the model's joined line is often not one
        # exact substring. Accept it when it matches ignoring whitespace, or when every word in it appears in
        # the source (the model only re-joined words, it added none).
        if raw in source_text or _squash(raw) in source_squashed:
            grounding = 'exact'
        elif _tokens(raw) and set(_tokens(raw)) <= source_tokens:
            grounding = 'words_in_source'
        else:
            item = extract_rule_line(raw, idx)
            for f in ('material', 'form', 'grade', 'thickness_in', 'width_in', 'length_in', 'quantity', 'standard_required'):
                item[f] = None
            item['extraction_source'] = 'nicrron_live_unverified'
            item['grounding'] = 'not_found_in_source'
            lines.append(item)
            continue
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
        item['extraction_source'] = 'nicrron_live_plus_validation'
        lines.append(item)
    return lines


def extract_live(text: str) -> tuple[list[dict], dict]:
    raw_json, model, latency_ms = _completion([
        {"role":"system", "content":SYSTEM_PROMPT},
        {"role":"user", "content":text},
    ], max_tokens=int(os.getenv("NICRRON_EXTRACT_MAX_TOKENS", "8000")), purpose="rfq_extract")
    try:
        result = Extraction.model_validate(_parse_json(raw_json))
    except (ValidationError, ValueError) as exc:
        raise GatewayResponseError("Model output failed schema validation: " + str(exc)[:220]) from exc

    return _grounded_lines(result, text), {
        "mode":"live_gateway", "gateway":"Nicrron", "model":model,
        "latency_ms":latency_ms, "validation":"source-grounded + deterministic"
    }


def extract_live_from_image(image_bytes: bytes, mime: str) -> tuple[list[dict], dict, str]:
    """One multimodal Nicrron call: structured lines + grounding source_text. Target <25s."""
    if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        raise GatewayResponseError(f"Unsupported image MIME type for vision: {mime}")
    prepared, out_mime = _prepare_vision_image(image_bytes, mime)
    vision_model = os.getenv("NICRRON_VISION_MODEL", DEFAULT_VISION_MODEL)
    vision_timeout = float(os.getenv("NICRRON_VISION_TIMEOUT_SECONDS", str(DEFAULT_VISION_TIMEOUT_SECONDS)))
    data_url = f"data:{out_mime};base64," + base64.b64encode(prepared).decode("ascii")
    raw_json, model, latency_ms = _completion(
        [
            {"role": "system", "content": IMAGE_EXTRACT_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract only metal sheet/plate RFQ lines from this image."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        max_tokens=1400,
        model=vision_model,
        timeout_seconds=vision_timeout,
        purpose="rfq_image_extract",
    )
    try:
        payload = _parse_json(raw_json)
        result = ImageExtraction.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        raise GatewayResponseError("Vision model output failed schema validation: " + str(exc)[:220]) from exc
    source_text = result.source_text.strip()
    if not source_text:
        raise GatewayResponseError("Vision model returned empty source_text")
    extraction = Extraction(lines=result.lines)
    lines = _grounded_lines(extraction, source_text)
    return lines, {
        "mode": "live_gateway",
        "gateway": "Nicrron",
        "model": model,
        "vision_model": model,
        "latency_ms": latency_ms,
        "vision_latency_ms": latency_ms,
        "source": "image_multimodal",
        "validation": "source-grounded + deterministic",
        "image_bytes_in": len(image_bytes),
        "image_bytes_sent": len(prepared),
    }, source_text
