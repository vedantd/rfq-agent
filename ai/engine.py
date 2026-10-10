"""Pure RFQ normalization and deterministic quote logic.

LLMs may suggest specs; every candidate still passes the same hard validation.
All pricing and catalog data in this demo are synthetic.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any


def sample_catalog() -> list[dict[str, Any]]:
    base = dict(material="stainless_steel", form="sheet", standard="ASTM A240/A240M", currency="USD",
                certificate_types=["MTR"], documents_verified=True, country_of_origin="US",
                price_source="SYNTHETIC_DEMO_COST", benchmark_source="SYNTHETIC_DEMO_BENCHMARK",
                benchmark_as_of="2026-10-10", last_verified_at="2026-10-10")
    return [
        dict(base, sku="SS-304-16GA-4896", grade="304", thickness_in=0.0625,
             width_in=48, length_in=96, supplier="Northstar Metals (demo)", supplier_cost_usd=200,
             benchmark_usd=255, lead_time_days=7),
        dict(base, sku="SS-304-125-4896", grade="304", thickness_in=0.125,
             width_in=48, length_in=96, supplier="Northstar Metals (demo)", supplier_cost_usd=310,
             benchmark_usd=405, lead_time_days=9),
        dict(base, sku="SS-316-125-4896", grade="316", thickness_in=0.125,
             width_in=48, length_in=96, supplier="Atlantic Steel (demo)", supplier_cost_usd=410,
             benchmark_usd=525, lead_time_days=10),
        dict(base, sku="SS-304-125-2448", grade="304", thickness_in=0.125,
             width_in=24, length_in=48, supplier="Northstar Metals (demo)", supplier_cost_usd=165,
             benchmark_usd=215, lead_time_days=7),
        dict(base, sku="SS-316-16GA-4896", grade="316", thickness_in=0.0625,
             width_in=48, length_in=96, supplier="Atlantic Steel (demo)", supplier_cost_usd=260,
             benchmark_usd=320, lead_time_days=7),
    ]


def tokenize_lines(text: str) -> list[str]:
    # Sentence boundaries retain decimal measurements such as 0.060.
    chunks = re.split(r"\n+|;|(?<=[.!?])\s+(?=[A-Z])|\b(?=also\s+\d+\s+sheets?\b)", text, flags=re.I)
    lines = [c.strip(' .,!\t') for c in chunks if re.search(r"\b(stainless|ss|steel|sheets?|plates?)\b", c, flags=re.I)]
    # Don't turn 'Please send pricing' into an item; reject narration without a material and no product.
    return [c for c in lines if re.search(r"\b(stainless|ss|304|316|steel)\b", c, flags=re.I)]


def extract_rule_line(raw: str, index: int) -> dict:
    s = raw.lower()
    material = "stainless_steel" if re.search(r"\b(stainless|ss)\b", s) else ("carbon_steel" if "carbon steel" in s else None)
    form = "sheet" if re.search(r"\bsheets?\b", s) else ("plate" if re.search(r"\bplates?\b",s) else None)
    grade_match = re.search(r"\b(316l|316|304|a36)\b", s)
    grade = grade_match.group(1).upper() if grade_match else None
    qty_match = re.search(r"\b(\d+)\s*(?:sheets?|plates?|pcs?|pieces?)\b",s)
    if not qty_match:
        qty_match = re.search(r"\bqty\s*[:=]?\s*(\d+)\b",s)
    quantity = int(qty_match.group(1)) if qty_match else None
    gauge = re.search(r"\b(\d{1,2})\s*(?:ga|gauge)\b",s)
    fraction = re.search(r"\b(\d{1,2})\s*/\s*(\d{1,2})\s*(?:in\b|inch\b|\"|thick\b)?",s)
    thick = re.search(r"\b(0\.\d+)\s*(?:in\b|inch\b|\")",s)
    thickness_in = None
    if gauge:
        # This shorthand is only resolved for stainless steel; gauge tables vary by material.
        thickness_in = {16: 0.0625, 18: 0.0500, 14: 0.078125}.get(int(gauge.group(1))) if material == 'stainless_steel' else None
    elif fraction and int(fraction.group(2)):
        thickness_in = round(int(fraction.group(1)) / int(fraction.group(2)), 6)
    elif thick:
        thickness_in = float(thick.group(1))
    # Avoid interpreting 1/8 as sheet dimensions; only detect x or multiplication glyph.
    size = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:x|×)\s*(\d+(?:\.\d+)?)(?:\s*(ft|feet|in|inch|inches))?\b",s)
    width_in = length_in = None
    if size:
        a, b = float(size.group(1)), float(size.group(2))
        unit = size.group(3)
        if unit in ('ft','feet') or (unit is None and a <= 12 and b <= 12):
            a, b = a*12, b*12
        width_in, length_in = sorted([a,b])
    explicit_standard = re.search(r"\b(ASTM\s+[A-Z]\d+(?:\s*/\s*[A-Z]\d+)?)\b",raw,re.I)
    required_certs = ["MTR"] if re.search(r"\b(mtr|mill\s+(?:test\s+)?(?:cert|certificate|report)s?)\b",s) else []
    country_required = bool(re.search(r"\b(country of origin|coo|us origin|usa origin)\b",s))
    return {"id":f"line_{index:03d}", "raw_text":raw, "material":material,"form":form,
            "grade":grade,"thickness_in":thickness_in,"width_in":width_in,"length_in":length_in,
            "quantity":quantity,"unit":"sheet" if form=='sheet' else "piece",
            "standard_required": explicit_standard.group(1).upper().replace(' ','') if explicit_standard else None,
            "required_certificates":required_certs,"country_of_origin_required":country_required,
            "extraction_source":"rules_demo", "approval_status":"pending"}


def extract_rules(text: str) -> list[dict]:
    return [extract_rule_line(c,i) for i,c in enumerate(tokenize_lines(text),start=1)]


def money(v: Any) -> float:
    return float(Decimal(str(v)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))


def analyze_line(line: dict, catalog: list[dict], markup: float = 0.225) -> dict:
    """Safe quote gate: missing/ambiguous critical fields never become a fabricated match."""
    line = dict(line)
    missing = [f for f in ("material","form","grade","thickness_in","width_in","length_in","quantity") if line.get(f) is None]
    line["clarifications"] = [{"field":f,"question":question_for(f,line)} for f in missing]
    line.update(match=None, pricing=None, compliance={"status":"not_evaluated","issues":[]},
                match_candidates=[], blockers=list(missing))
    if missing:
        line["status"] = "needs_clarification"
        line["approval_status"] = "pending"
        return line
    if line['quantity'] <= 0:
        line['status'] = 'needs_clarification'
        line['blockers'] = ['quantity must be positive']
        line['clarifications'] = [{"field":"quantity","question":"How many units are required?"}]
        return line
    candidates = []
    for item in catalog:
        if any(item.get(f) != line.get(f) for f in ('material','form','grade')):
            continue
        if abs(float(item['thickness_in'])-float(line['thickness_in'])) > 0.003:
            continue
        if sorted([float(item['width_in']),float(item['length_in'])]) != sorted([float(line['width_in']),float(line['length_in'])]):
            continue
        if line.get('standard_required') and line['standard_required'].replace(' ','') not in item.get('standard','').replace(' ',''):
            continue
        candidates.append(item)
    line['match_candidates'] = [it['sku'] for it in candidates]
    if len(candidates) != 1:
        line['status'] = 'needs_clarification' if len(candidates)==0 else 'needs_review'
        line['blockers'] = ['no verified compatible catalog SKU' if not candidates else 'multiple compatible SKUs']
        line['clarifications'] = [{"field":"sku","question":"Can you confirm your required specifications or preferred product SKU?"}]
        line['approval_status'] = 'pending'
        return line
    it = candidates[0]
    thickness_delta = abs(float(it['thickness_in']) - float(line['thickness_in']))
    line['match'] = {
        'sku':it['sku'], 'supplier':it['supplier'], 'matched_grade':it['grade'],
        'supplier_standard':it['standard'], 'thickness_tolerance_in':0.003,
        'thickness_difference_in':round(thickness_delta,6),
        'reason': 'Grade, material, form and dimensions match; thickness is within the declared 0.003-in tolerance.'
    }
    supplier = money(it['supplier_cost_usd'])
    unit = money(supplier * (1 + markup))
    bench = money(it['benchmark_usd'])
    line['pricing'] = {
        'supplier_cost_usd':supplier, 'markup_pct':money(markup*100), 'unit_price_usd':unit,
        'quantity':line['quantity'],'line_total_usd':money(unit*line['quantity']),
        'benchmark_unit_usd':bench, 'benchmark_source':it['benchmark_source'],
        'benchmark_as_of':it['benchmark_as_of'],
        'below_benchmark_pct':money(((bench-unit)/bench)*100) if bench else None,
        'explanation':f'Cost ${supplier:.2f} × (1 + {markup*100:g}% markup) = ${unit:.2f}; compared with a synthetic demo benchmark of ${bench:.2f}.',
        'data_is_synthetic': it['price_source'].startswith('SYNTHETIC') or it['benchmark_source'].startswith('SYNTHETIC')
    }
    issues=[]
    for cert in line.get('required_certificates',[]):
        if cert not in it.get('certificate_types',[]):
            issues.append(f'{cert} is not listed by supplier')
        elif not it.get('documents_verified',False):
            issues.append(f'{cert} document not verified')
    if line.get('country_of_origin_required') and not it.get('country_of_origin'):
        issues.append('Country of origin evidence unavailable')
    line['compliance'] = {
        'status':'pass' if not issues else 'blocked', 'issues':issues,
        'available_certificates':it.get('certificate_types',[]),
        'documents_verified':it.get('documents_verified',False),
        'country_of_origin':it.get('country_of_origin'),
        'supplier_standard':it.get('standard'),
        'note':'Document verification and standards are supplier-record assertions, not an independently performed inspection.'
    }
    line['blockers'] = issues
    line['clarifications'] = []
    line['status'] = 'blocked_compliance' if issues else ('approved' if line.get('approval_status')=='approved' else 'ready_for_approval')
    if issues: line['approval_status'] = 'pending'
    return line


def question_for(field: str,line:dict) -> str:
    q={
      'material':'What material do you need (for example stainless steel or carbon steel)?',
      'form':'Is this sheet, plate, or another product form?',
      'grade':'What material grade is required (for example 304 or 316 stainless steel)?',
      'thickness_in':'What sheet thickness or gauge do you require?',
      'width_in':'What sheet width and length are required?',
      'length_in':'What sheet width and length are required?',
      'quantity':'How many sheets or pieces do you need?'
    }
    return q[field]


def summarize(rfq:dict)->dict:
    lines=rfq.get('lines',[])
    return {
      'rfq_id':rfq['id'],'tenant_id':rfq['tenant_id'],'buyer_id':rfq['buyer_id'],
      'buyer_email':rfq.get('buyer_email'),'status': 'needs_clarification' if any(x['status']=='needs_clarification' for x in lines) else 'review_required' if any(x['status']!='approved' for x in lines) else 'approved',
      'parser_mode':rfq.get('parser_mode'), 'gateway':rfq.get('gateway'),
      'line_count':len(lines),
      'ready_for_approval':sum(x['status']=='ready_for_approval' for x in lines),
      'needs_clarification':sum(x['status']=='needs_clarification' for x in lines),
      'approved':sum(x['status']=='approved' for x in lines),
      'lines':lines,'events':rfq.get('events',[]), 'created_at':rfq['created_at']
    }
