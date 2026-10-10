"""The LLM tasks. Each one has a deterministic fallback, so the pipeline runs with LLM_PROVIDER=rules."""
from __future__ import annotations

import json

from .providers import LLMProvider, ProviderUnavailable
from .tracing import Run

NULLABLE_STR = {"type": ["string", "null"]}
NULLABLE_NUM = {"type": ["number", "null"]}

EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["reference", "buyer_name", "buyer_company", "buyer_email", "requirements", "lines"],
    "properties": {
        "reference": NULLABLE_STR, "buyer_name": NULLABLE_STR, "buyer_company": NULLABLE_STR, "buyer_email": NULLABLE_STR,
        "requirements": {"type": "array", "items": {"type": "string"}},
        "lines": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["line_no", "raw_text", "qty", "uom", "notes"],
            "properties": {"line_no": {"type": "integer"}, "raw_text": {"type": "string"}, "qty": NULLABLE_NUM,
                           "uom": NULLABLE_STR, "notes": NULLABLE_STR}}},
    },
}
EXTRACT_SYSTEM = """You read requests for quotes (RFQs) for industrial metal products: emails, forms, spreadsheets, photos and scans.
Find every requested item and copy it exactly as the buyer wrote it, abbreviations and all, into raw_text. Never normalize, correct or complete an item; a later step does that.
qty is the number requested, or null when it is missing, TBD or unclear. uom is the unit as written (ea, sheets, ft, lengths...), or null.
Put per-line remarks (e.g. "confirm with architect") in notes.
requirements: copy, verbatim, every sentence about certifications (MTR, mill certs, EN 10204), country of origin, Buy America / FTA / DFARS, substitutions, LEED, finishes standards (AAMA), delivery or due dates, quote validity.
Ignore superseded or old revisions of a list. Don't invent items."""

SPEC_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["material_family", "grade", "temper", "shape", "finish"],
    "properties": {
        "material_family": {"type": ["string", "null"], "enum": ["stainless steel", "aluminum", "galvanized steel", "carbon steel", "brass", "other", None]},
        "grade": NULLABLE_STR, "temper": NULLABLE_STR,
        "shape": {"type": ["string", "null"], "enum": ["sheet", "plate", "round tube", "square tube", "rect tube", "angle", "channel", "flat bar", "tread plate", "HSS square", "other", None]},
        "finish": NULLABLE_STR,
    },
}

QUESTIONS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["questions", "email_subject", "email_body"],
    "properties": {
        "questions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                 "required": ["line_id", "question"],
                                                 "properties": {"line_id": {"type": "string"}, "question": {"type": "string"}}}},
        "email_subject": {"type": "string"}, "email_body": {"type": "string"},
    },
}

ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["grade", "temper", "finish", "gauge", "thickness_in", "width_in", "height_in", "length_in", "qty", "remove_line"],
    "properties": {"grade": NULLABLE_STR, "temper": NULLABLE_STR, "finish": NULLABLE_STR, "gauge": {"type": ["integer", "null"]},
                   "thickness_in": NULLABLE_NUM, "width_in": NULLABLE_NUM, "height_in": NULLABLE_NUM, "length_in": NULLABLE_NUM,
                   "qty": NULLABLE_NUM, "remove_line": {"type": "boolean"}},
}


def _call(provider: LLMProvider, run: Run | None, purpose: str, **kw):
    try:
        res = provider.complete_json(**kw)
    except ProviderUnavailable as e:
        if run:
            run.llm_call(purpose=purpose, provider=provider.name, model=provider.model, prompt=kw["prompt"], output="",
                         latency_ms=0, error=str(e))
        raise
    if run:
        run.llm_call(purpose=purpose, provider=provider.name, model=res.model, prompt=kw["prompt"], output=res.raw_text,
                     latency_ms=res.latency_ms, input_tokens=res.input_tokens, output_tokens=res.output_tokens)
    return res.data


def extract(provider: LLMProvider, *, text: str, attachments, run: Run | None) -> dict:
    prompt = "Extract the RFQ." + (f"\n\nRFQ text:\n<rfq>\n{text}\n</rfq>" if text.strip() else " It is in the attached file.")
    return _call(provider, run, "extract_lines", system=EXTRACT_SYSTEM, prompt=prompt, schema=EXTRACT_SCHEMA,
                 schema_name="rfq_extraction", attachments=attachments)


def spec_hint(provider: LLMProvider, raw: str, run: Run | None) -> dict:
    prompt = (f"RFQ line: <line>{raw}</line>\nIdentify the material family, grade/alloy, temper, product shape and finish, "
              "only where the line states them or uses an unambiguous trade abbreviation. Use null for anything not stated.")
    return _call(provider, run, "spec_hint", system="You are a metals service-center estimator.", prompt=prompt,
                 schema=SPEC_SCHEMA, schema_name="line_spec", max_tokens=2000)


def write_questions(provider: LLMProvider, rfq: dict, items: list[dict], run: Run | None) -> dict:
    prompt = (
        "Rewrite these clarifying questions for the buyer so each is short, specific and polite, then write one email "
        "that asks all of them. Keep every fact, option, number and line number exactly; don't add options or guess answers. "
        "Say that the other lines are priced and will be on the quote.\n\n"
        f"Buyer: {rfq.get('buyer') or {}}\nRFQ reference: {rfq.get('reference')}\nSubject: {(rfq.get('source') or {}).get('subject')}\n"
        f"Lines quotable now: {rfq['summary']['quotable']} of {rfq['summary']['lines']}\n\n"
        f"Questions (JSON):\n{json.dumps(items, indent=1)}\n\nSign the email as 'Gowanus Metal Supply - Inside Sales'."
    )
    return _call(provider, run, "clarifying_questions", system="You write for an industrial metals distributor's inside sales team.",
                 prompt=prompt, schema=QUESTIONS_SCHEMA, schema_name="clarifications")


def interpret_answer(provider: LLMProvider, line: dict, answer: str, run: Run | None) -> dict:
    prompt = (f"RFQ line {line['line_no']}: \"{line['raw']}\"\nWe asked: {line.get('question')}\nBuyer answered: \"{answer}\"\n"
              "Return only the fields the answer sets (null otherwise). thickness/sizes in inches, lengths in inches. "
              "remove_line is true only if the buyer says to drop the line.")
    return _call(provider, run, "interpret_answer", system="You are a metals service-center estimator.", prompt=prompt,
                 schema=ANSWER_SCHEMA, schema_name="answer_fields", max_tokens=2000)


def template_email(rfq: dict, items: list[dict]) -> dict:
    buyer = (rfq.get("buyer") or {}).get("name") or ""
    first = buyer.split()[0] if buyer else "there"
    subj = (rfq.get("source") or {}).get("subject") or rfq.get("reference") or "your RFQ"
    s = rfq["summary"]
    body = [f"Hi {first},", "",
            f"Thanks for the RFQ. {s['quotable']} of {s['lines']} lines are priced and will be on the quote. "
            "Before we price the rest, we need a few answers:", ""]
    body += [f"- {it['question']}" for it in items]
    body += ["", "Reply inline and we'll send the full quote.", "", "Gowanus Metal Supply - Inside Sales"]
    return {"subject": f"Re: {subj} - {len(items)} question(s) before we quote", "body": "\n".join(body)}
