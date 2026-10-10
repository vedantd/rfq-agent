"""RFQ pipeline: ingest -> extract -> parse -> match/price/comply -> clarify. Plus clarification, approval and quotes."""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from . import agent, engine, store
from .ingest import Ingested, Row
from .parse import parse_line
from .providers import ProviderUnavailable, get_provider
from .refdata import ref
from .tracing import Run

SELLER = "Gowanus Metal Supply"


class PipelineError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _buyer_from(ing: Ingested, text: str) -> dict:
    b = {"name": None, "company": None, "email": None}
    frm = ing.meta.get("from") or ""
    m = re.match(r"\s*\"?([^\"<]+?)\"?\s*<([^>]+)>", frm)
    if m:
        b["name"], b["email"] = m[1].strip(), m[2].strip()
    m = re.search(r"\bBuyer\s+([A-Z][\w.]*\s+[A-Z][\w]+)", text)
    if m and not b["name"]:
        b["name"] = m[1]
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    if m and not b["email"]:
        b["email"] = m[0]
    return b


def _reference(ing: Ingested, text: str) -> str | None:
    m = re.search(r"RFQ\s*(?:No\.?|#)\s*:?\s*([A-Z0-9][A-Z0-9-]+)", text, re.I)
    if m:
        return m[1]
    return ing.meta.get("subject") or None


def summarize(rfq: dict):
    lines = [l for l in rfq["lines"] if l["status"] != "REMOVED"]
    by = lambda s: sum(1 for l in lines if l["status"] == s)
    quotable = [l for l in lines if l["status"] in ("MATCH", "MATCH_ASSUMPTION") and l["compliance"]["result"] != "BLOCK"]
    open_q = [l for l in lines if l.get("question") and not l.get("approved")]
    rfq["summary"] = {
        "lines": len(lines), "match": by("MATCH"), "match_assumption": by("MATCH_ASSUMPTION"), "clarify": by("CLARIFY"),
        "no_match": by("NO_MATCH"), "blocked": sum(1 for l in lines if l["compliance"]["result"] == "BLOCK"),
        "quotable": len(quotable), "approved": sum(1 for l in lines if l.get("approved")), "open_questions": len(open_q),
        "quotable_value": round(sum((l["price"] or {}).get("extended") or 0 for l in quotable), 2),
    }
    rfq["status"] = "needs_clarification" if open_q else "ready_to_quote"


def _mark_duplicates(lines: list[dict]):
    seen = {}
    for l in lines:
        l["duplicate_of"] = None
        if l["status"] not in ("MATCH", "MATCH_ASSUMPTION"):
            continue
        s = l["spec"]
        k = (s["material_family"], s["grade"], s["shape"], s["finish"], s["thickness_in"], s["width_in"], s["length_in"], s["height_in"])
        if k in seen:
            first = seen[k]
            l["duplicate_of"] = first["line_id"]
            total = (first.get("qty_ea") or 0) + (l.get("qty_ea") or 0)
            l["question"] = l.get("question") or (
                f"Line {l['line_no']} looks like the same item as line {first['line_no']} ({engine.describe_spec(s)}). "
                f"Combine them into {total:g} pieces?")
        else:
            seen[k] = l


def _build_line(i: int, row: Row, provider, run) -> dict:
    p = parse_line(row.raw, row.qty_hint, row.uom_hint)
    if row.qty_hint is not None and p["qty"] is None and str(row.qty_hint).strip():
        p["notes"].append(f"Quantity given as '{row.qty_hint}'")
    line = {"line_id": f"L{i}", "line_no": row.line_no, "raw": p["raw"], "qty": p["qty"], "uom": p["uom"],
            "qty_raw": p["qty_raw"], "row_notes": row.notes, "spec": p["spec"], "notes": p["notes"],
            "parse_assumptions": p["assumptions"], "approved": False, "approved_at": None, "history": []}
    s = p["spec"]
    if provider.name != "rules" and (s["material_family"] is None or s["shape"] is None):
        try:
            hint = agent.spec_hint(provider, row.raw, run)
            for k in ("material_family", "grade", "temper", "shape", "finish"):
                if s.get(k) is None and hint.get(k) not in (None, "other"):
                    s[k] = hint[k]
                    line["notes"].append(f"{k.replace('_', ' ')} read by the LLM: {hint[k]}")
        except ProviderUnavailable:
            pass
    return line


def _clarifications(rfq: dict, provider, run) -> None:
    items = [{"line_id": l["line_id"], "line_no": l["line_no"], "question": l["question"]}
             for l in rfq["lines"] if l.get("question") and l["status"] != "REMOVED" and not l.get("approved")]
    rfq["clarification_email"] = None
    if not items:
        return
    if provider.name != "rules":
        try:
            out = agent.write_questions(provider, rfq, items, run)
            by_id = {q["line_id"]: q["question"] for q in out.get("questions", [])}
            for l in rfq["lines"]:
                if l["line_id"] in by_id:
                    l["question_template"] = l["question"]
                    l["question"] = by_id[l["line_id"]]
            rfq["clarification_email"] = {"subject": out["email_subject"], "body": out["email_body"], "written_by": provider.model}
            return
        except ProviderUnavailable:
            pass
    rfq["clarification_email"] = {**agent.template_email(rfq, items), "written_by": "template"}


def process(ing: Ingested, *, run_name: str = "ingest") -> dict:
    provider = get_provider()
    rfq_id = "rfq_" + secrets.token_hex(4)
    run = Run(rfq_id, run_name)
    warnings = list(ing.warnings)
    rows, header = ing.rows, ing.header_text
    reference = buyer = None

    with run.span("extract", source=ing.source_type, provider=provider.name) as meta:
        use_llm = ing.needs_llm or (provider.name != "rules" and not ing.meta.get("table"))
        if use_llm:
            if ing.needs_llm and provider.name == "rules":
                raise PipelineError(422, "This file has no readable text (image or scan). Reading it needs an LLM: "
                                         "set LLM_PROVIDER=claude (ANTHROPIC_API_KEY) or nicrron (NICRRON_API_KEY).")
            try:
                ext = agent.extract(provider, text=ing.full_text, attachments=ing.attachments, run=run)
                rows = [Row(l["line_no"], l["raw_text"], l["qty"], l["uom"], l["notes"]) for l in ext["lines"]]
                header = "\n".join([header, *ext["requirements"]]).strip()
                reference = ext.get("reference")
                buyer = {"name": ext.get("buyer_name"), "company": ext.get("buyer_company"), "email": ext.get("buyer_email")}
                meta["extracted_by"] = provider.model
            except ProviderUnavailable as e:
                if ing.needs_llm:
                    raise PipelineError(502, f"The LLM could not read this file: {e}")
                warnings.append(f"LLM extraction failed ({e}); used the rule-based reader instead")
                meta["extracted_by"] = "rules (fallback)"
        else:
            meta["extracted_by"] = "rules"
        meta["rows"] = len(rows)
    if not rows:
        raise PipelineError(422, "No line items were found in this RFQ.")

    with run.span("parse", lines=len(rows)):
        lines = [_build_line(i + 1, r, provider, run) for i, r in enumerate(rows)]

    all_text = "\n".join([header, *(l["raw"] for l in lines), *((l["row_notes"] or "") for l in lines)])
    requirements = engine.detect_requirements(all_text)
    catalog = store.catalog_all()
    with run.span("match_price_comply", requirements=sorted(requirements)):
        for l in lines:
            engine.evaluate(l, catalog, requirements)
        _mark_duplicates(lines)

    rfq = {
        "id": rfq_id, "created_at": _now(), "updated_at": _now(),
        "source": {"type": ing.source_type, "filename": ing.filename, **{k: v for k, v in ing.meta.items() if k != "table"}},
        "reference": reference or _reference(ing, header),
        "buyer": buyer or _buyer_from(ing, header),
        "header_text": header, "requirements": requirements, "warnings": warnings,
        "lines": lines, "quotes": [],
        "provider": {"name": provider.name, "model": provider.model},
    }
    summarize(rfq)
    with run.span("clarify", open_questions=rfq["summary"]["open_questions"]):
        _clarifications(rfq, provider, run)
    s = rfq["summary"]
    rfq["trace"] = run.finish(
        input_text=ing.full_text or f"[{ing.source_type} file {ing.filename}]",
        output_summary=(f"{s['lines']} lines: {s['match']} match, {s['match_assumption']} match with assumption, "
                        f"{s['clarify']} clarify, {s['no_match']} no match, {s['blocked']} compliance blocks. "
                        f"Quotable value ${s['quotable_value']:,.2f}. Open questions: {s['open_questions']}."),
        metadata={"summary": s, "requirements": sorted(requirements), "provider": provider.name},
    )
    store.save_rfq(rfq)
    return rfq


# ---------- clarification / approval / quote ----------
def get(rfq_id: str) -> dict:
    rfq = store.get_rfq(rfq_id)
    if not rfq:
        raise PipelineError(404, f"RFQ {rfq_id} not found")
    return rfq


def _line(rfq: dict, line_id: str) -> dict:
    for l in rfq["lines"]:
        if l["line_id"] == line_id:
            return l
    raise PipelineError(404, f"Line {line_id} not found on {rfq['id']}")


SPEC_FIELDS = {"material_family", "grade", "temper", "shape", "finish", "thickness_in", "gauge", "width_in", "height_in", "length_in"}


def apply_clarification(rfq_id: str, line_id: str, body: dict) -> dict:
    """body: {answer?: str, qty?: number, spec?: {field: value}, remove?: bool, selected_sku?: str}"""
    rfq = get(rfq_id)
    line = _line(rfq, line_id)
    provider = get_provider()
    run = Run(rfq_id, f"clarify:{line_id}")
    before = {"status": line["status"], "spec": dict(line["spec"]), "qty": line["qty"]}
    answer = (body.get("answer") or "").strip()

    with run.span("apply_answer", line_id=line_id, has_answer=bool(answer)):
        if body.get("remove"):
            line["status"] = "REMOVED"
        else:
            if answer:
                if re.fullmatch(r"\d+(\.\d+)?", answer) and line["qty"] is None:
                    line["qty"] = float(answer) if "." in answer else int(answer)
                else:
                    combined = parse_line(f"{line['raw']} {answer}", line["qty"] if line["qty"] is not None else None, line["uom"])
                    for k, v in combined["spec"].items():
                        if v is not None and (line["spec"].get(k) is None or k in ("grade", "finish", "temper") and v != line["spec"].get(k)):
                            line["spec"][k] = v
                    line["parse_assumptions"] = combined["assumptions"]
                    if line["qty"] is None and combined["qty"] is not None:
                        line["qty"] = combined["qty"]
                if provider.name != "rules":
                    try:
                        fields = agent.interpret_answer(provider, line, answer, run)
                        if fields.get("remove_line"):
                            line["status"] = "REMOVED"
                        for k in ("grade", "temper", "finish", "thickness_in", "width_in", "height_in", "length_in"):
                            if fields.get(k) not in (None, ""):
                                line["spec"][k] = fields[k]
                        if fields.get("gauge"):
                            g = int(fields["gauge"])
                            tbl = ref().sheet_gauge.get(line["spec"]["material_family"] or "", {})
                            line["spec"]["gauge"] = g
                            if g in tbl:
                                line["spec"]["thickness_in"] = tbl[g]
                        if fields.get("qty") is not None:
                            line["qty"] = fields["qty"]
                    except ProviderUnavailable:
                        pass
            if body.get("qty") is not None:
                line["qty"] = body["qty"]
            for k, v in (body.get("spec") or {}).items():
                if k not in SPEC_FIELDS:
                    raise PipelineError(400, f"Unknown spec field '{k}'. Allowed: {', '.join(sorted(SPEC_FIELDS))}")
                line["spec"][k] = v
            if line["status"] != "REMOVED":
                engine.evaluate(line, store.catalog_all(), rfq["requirements"])
                if body.get("selected_sku"):
                    _select(line, body["selected_sku"], rfq)
        line["approved"] = False
        line["history"].append({"at": _now(), "answer": answer or None, "fields": {k: v for k, v in body.items() if k != "answer"},
                                "before": before, "after": {"status": line["status"], "spec": dict(line["spec"]), "qty": line["qty"]}})
    _mark_duplicates([l for l in rfq["lines"] if l["status"] != "REMOVED"])
    summarize(rfq)
    _clarifications(rfq, provider, run)
    rfq["updated_at"] = _now()
    run.finish(input_text=f"Line {line['line_no']}: {line['raw']}\nBuyer answer: {answer or body}",
               output_summary=f"{before['status']} -> {line['status']}" + (f"; open question: {line['question']}" if line.get("question") else ""),
               metadata={"line_id": line_id})
    store.save_rfq(rfq)
    return rfq


def _select(line: dict, sku: str, rfq: dict):
    if sku not in line["candidates"]:
        raise PipelineError(409, f"{sku} is not an eligible SKU for line {line['line_no']}. Eligible: {', '.join(line['candidates']) or 'none'}")
    item = store.catalog_get(sku)
    flags = engine.compliance_flags(item, line, rfq["requirements"])
    line["selected_sku"] = sku
    line["item"] = {k: item.get(k) for k in ("sku", "description", "standard", "dual_cert", "mill", "country_of_origin",
                                               "country_of_melt", "stock_qty", "lead_time_days", "certifications", "mtr_type")}
    line["price"] = engine.price_line(item, line["qty_ea"])
    line["compliance"] = {"result": engine.worst(flags), "flags": flags}
    line["selection_reason"] = f"{sku} chosen by the user."


def approve(rfq_id: str, line_id: str, body: dict) -> dict:
    rfq = get(rfq_id)
    line = _line(rfq, line_id)
    if line["status"] not in ("MATCH", "MATCH_ASSUMPTION"):
        raise PipelineError(409, f"Line {line['line_no']} is {line['status']}; resolve its question before approving.")
    if body.get("sku"):
        _select(line, body["sku"], rfq)
    if line["compliance"]["result"] == "BLOCK" and not body.get("override_block"):
        raise PipelineError(409, f"Line {line['line_no']} fails a compliance rule. Send override_block: true to approve it anyway, "
                                 "and it will be quoted as non-compliant.")
    line["approved"] = True
    line["approved_at"] = _now()
    line["approved_note"] = body.get("note")
    if body.get("override_block"):
        line["compliance"]["override"] = True
    summarize(rfq)
    rfq["updated_at"] = _now()
    store.save_rfq(rfq)
    return line


def draft_quote(rfq_id: str, body: dict) -> dict:
    rfq = get(rfq_id)
    approved_only = bool(body.get("approved_only", False))
    items, excluded = [], []
    for l in rfq["lines"]:
        if l["status"] == "REMOVED":
            excluded.append({"line_no": l["line_no"], "raw": l["raw"], "reason": "Removed at the buyer's request"})
            continue
        ok = l["status"] in ("MATCH", "MATCH_ASSUMPTION") and (l["compliance"]["result"] != "BLOCK" or l["compliance"].get("override"))
        if approved_only and not l.get("approved"):
            ok = False
        if not ok:
            reason = l.get("question") or {"CLARIFY": "Needs clarification", "NO_MATCH": "Not stocked"}.get(l["status"], "Not approved")
            excluded.append({"line_no": l["line_no"], "raw": l["raw"], "status": l["status"], "reason": reason})
            continue
        item, price = l["item"], l["price"] or {}
        qty = l["qty_ea"]
        lead = 0 if (item.get("stock_qty") or 0) >= (qty or 0) else item.get("lead_time_days")
        items.append({
            "line_no": l["line_no"], "buyer_text": l["raw"], "sku": l["selected_sku"], "description": item["description"],
            "standard": item.get("standard"), "qty": qty, "uom": "EA", "unit_price": price.get("unit_price"),
            "extended": price.get("extended"), "price_basis": price.get("tier"), "price_per_lb": price.get("price_per_lb"),
            "price_rationale": price.get("rationale"), "benchmark_position": price.get("position"),
            "lead_time_days": lead, "country_of_origin": item.get("country_of_origin"), "country_of_melt": item.get("country_of_melt"),
            "certs": item.get("mtr_type") or item.get("certifications"),
            "compliance": l["compliance"]["result"] + (" (override: quoted as non-compliant)" if l["compliance"].get("override") else ""),
            "compliance_notes": [f["message"] for f in l["compliance"]["flags"] if f["severity"] != "OK"],
            "assumptions": l["assumptions"], "approved": l.get("approved", False),
        })
    subtotal = round(sum(i["extended"] or 0 for i in items), 2)
    valid_days = 30 if re.search(r"30 days", rfq.get("header_text") or "", re.I) else 15
    created = datetime.now(timezone.utc)
    quote = {
        "quote_id": f"Q-{rfq['id'][4:].upper()}-{len(rfq['quotes']) + 1}",
        "rfq_id": rfq["id"], "rfq_reference": rfq.get("reference"), "created_at": created.isoformat(),
        "valid_until": (created + timedelta(days=valid_days)).date().isoformat(),
        "seller": SELLER, "buyer": rfq.get("buyer"), "currency": "USD",
        "lines": items, "excluded_lines": excluded,
        "subtotal": subtotal, "freight": "Quoted separately", "terms": "Net 30",
        "requirements_acknowledged": [v["source"] for v in rfq["requirements"].values()],
        "clarifications_pending": [{"line_no": l["line_no"], "question": l["question"]} for l in rfq["lines"]
                                   if l.get("question") and l["status"] != "REMOVED" and not l.get("approved")],
        "notes": ["All prices are SYNTHETIC demo data, not real market prices."],
        "approved_only": approved_only,
    }
    rfq["quotes"].append(quote)
    rfq["updated_at"] = _now()
    store.save_rfq(rfq)
    return quote
