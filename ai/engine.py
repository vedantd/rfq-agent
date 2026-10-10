"""Pure RFQ normalization and deterministic quote logic.

LLMs may suggest specs; every candidate still passes the same hard validation.
All pricing and catalog data in this demo are synthetic.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any
import database


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
    
    # Material detection - expanded to handle more types
    material = None
    if re.search(r"\b(stainless|ss)\b", s):
        material = "stainless_steel"
    elif re.search(r"\b(galvanized|galv|hdg)\b", s):
        material = "galvanized_steel"
    elif re.search(r"\b(carbon steel|plain carbon|mild steel|a36)\b", s):
        material = "carbon_steel"
    elif re.search(r"\b(aluminum|alum|alm|6061|5052|3003)\b", s):
        material = "aluminum"
    elif re.search(r"\b(copper|brass|bronze)\b", s):
        material = "copper_alloy"
    
    # Form detection - expanded to handle tubes, angles, HSS, etc.
    form = None
    if re.search(r"\bplate[s]?\b", s):
        form = "plate"
    elif re.search(r"\btube[s]?\b", s) or re.search(r"\b(?:od|wall|od\s+ss)", s):
        form = "tube"
    elif re.search(r"\bangle[s]?\b", s) or re.search(r"\bl\s*\d+", s):
        form = "angle"
    elif re.search(r"\bhss\b", s):
        form = "hss"
    elif re.search(r"\b(sheets?|sht|pl)\b", s):
        if re.search(r"\btube\b", s) or re.search(r"\b(od|wall|od\s+ss)", s):
            form = "tube"
        elif re.search(r"\b(angle|l-shape|l_shape)\b", s):
            form = "angle"
        elif re.search(r"\b(hss|hollow)\b", s):
            form = "hss"
        else:
            form = "sheet"
    
    # Grade detection - more comprehensive
    grade_match = re.search(r"\b(316l|316|304|304l|a36|5052|6061|3003|2205|duplex)\b", s)
    grade = grade_match.group(1).upper() if grade_match else None
    
    # For galvanized steel without explicit grade, use a default
    if material == "galvanized_steel" and not grade:
        grade = None  # Galvanized sheets often don't have an explicit grade
    
    # Finish detection (e.g., 2B, #4, BA, mill, polished).
    # Do not treat "mill certs / mill test report" as a mill finish.
    finish = None
    finish_match = re.search(r"\b(?:#\d|2b|#2|#4|#8|ba|polished|bright|satin|raw)\b", s, flags=re.I)
    if finish_match:
        finish = finish_match.group(0).upper()
    elif re.search(r"\bmill\b", s) and not re.search(r"\bmill\s*(?:cert|test|report|mtr)s?\b", s):
        finish = "MILL"
    
    # Quantity detection - be careful not to match grade numbers
    qty_match = None
    # First try: explicit patterns with qty keyword
    qty_match = re.search(r"\bqty\s*[:=]?\s*(\d+)\b", s)
    if not qty_match:
        # Try patterns with parentheses or brackets
        qty_match = re.search(r"[\(\[]?\s*(\d+)\s*[\)\]]?\s*(?:sheets?|plates?|pcs?|pieces?|sticks?|lengths?|ea|each)\b", s)
    if not qty_match:
        # Try: "need N" pattern
        qty_match = re.search(r"\bneed[s]?\s*(\d+)\b", s)
    quantity = int(qty_match.group(1)) if qty_match else None
    
    # For tubes/forms, try to extract OD (outer diameter) as width
    od_match = None
    if form == 'tube':
        # Look for OD specification like "1-1/2" OD" or "1.5 OD"
        od_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\"\s*od\b", s)
        if od_match:
            # Parse the OD value (handle fractional like 1-1/2)
            od_whole = float(od_match.group(1))
            od_frac = float(od_match.group(2)) if od_match.group(2) else 0
            od_value = od_whole + od_frac / 10  # Simple concatenation for "1-1/2" -> 1.5
    
    # Gauge detection
    gauge = re.search(r"\b(\d{1,2})\s*(?:ga|gauge)\b", s)
    gauge_number = gauge.group(1) if gauge else None
    
    # Thickness detection
    fraction = re.search(r"\b(\d{1,2})\s*/\s*(\d{1,2})\s*(?:in\b|inch\b|\"|thick\b)?", s)
    thick = re.search(r"(?:^|[\s\(])([0]\.\d+|\.\d+)\s*(?:in\b|inch\b|\")?", s)
    metric_thick = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:mm|metric)\b", s)
    
    thickness_in = None
    thickness_assumption = None
    
    if metric_thick:
        # Convert mm to inches (approximate)
        mm_val = float(metric_thick.group(1))
        thickness_in = round(mm_val / 25.4, 4)
        thickness_assumption = f"Converted {mm_val}mm to {thickness_in:.4f}\" (metric assumption)"
    elif thick:
        thickness_in = float(thick.group(1))
    elif fraction and int(fraction.group(2)):
        thickness_in = round(int(fraction.group(1)) / int(fraction.group(2)), 6)
    elif gauge_number:
        # Use database gauge resolution
        result = resolve_gauge_to_thickness(gauge_number, material or "stainless_steel", form or "sheet")
        thickness_in = result['thickness_in']
        thickness_assumption = result['assumption']
    
    # Size detection - handle both inches and feet
    size = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:x|×)\s*(\d+(?:\.\d+)?)(?:\s*(ft|feet|in|inch|inches))?\b", s)
    width_in = length_in = None
    size_assumption = None
    
    if size:
        a, b = float(size.group(1)), float(size.group(2))
        unit = size.group(3)
        if unit in ('ft', 'feet') or (unit is None and a <= 12 and b <= 12):
            a, b = a * 12, b * 12
            if unit is None:
                size_assumption = f"Assumed {size.group(1)} x {size.group(2)} is in feet (converted to {a:.0f} x {b:.0f} inches)"
        width_in, length_in = sorted([a, b])
    
    # Metric dimensions (mm)
    metric_size = re.search(r"\b(\d+)\s*x\s*(\d+)\s*(?:mm|metric)\b", s)
    if metric_size and not width_in:
        a, b = float(metric_size.group(1)), float(metric_size.group(2))
        # Convert mm to inches
        width_in, length_in = sorted([a / 25.4, b / 25.4])
        size_assumption = f"Converted {metric_size.group(1)}x{metric_size.group(2)}mm to {width_in:.2f}x{length_in:.2f}\" (metric)"
    
    # Standard detection
    explicit_standard = re.search(r"\b(ASTM\s+[A-Z]\d+(?:\s*/\s*[A-Z]\d+)?)\b", raw, re.I)
    
    # Certificate requirements
    required_certs = ["MTR"] if re.search(r"\b(mtr|mill\s+(?:test\s+)?(?:cert|certificate|report)s?|mill cert)\b", s) else []
    
    # Country of origin requirement
    country_required = bool(re.search(r"\b(country of origin|coo|us origin|usa origin)\b", s))
    
    # Compliance triggers
    compliance_triggers = check_compliance_triggers(raw)
    
    return {
        "id": f"line_{index:03d}",
        "raw_text": raw,
        "material": material,
        "form": form,
        "grade": grade,
        "finish": finish,
        "thickness_in": thickness_in,
        "thickness_assumption": thickness_assumption,
        "width_in": width_in,
        "length_in": length_in,
        "size_assumption": size_assumption,
        "quantity": quantity,
        "unit": "sheet" if form in ('sheet', 'plate') else ("sticks" if form == 'tube' else "pcs"),
        "standard_required": explicit_standard.group(1).upper().replace(' ', '') if explicit_standard else None,
        "required_certificates": required_certs,
        "country_of_origin_required": country_required,
        "compliance_triggers": compliance_triggers,
        "extraction_source": "rules_demo",
        "approval_status": "pending",
    }


def extract_rules(text: str) -> list[dict]:
    return [extract_rule_line(c,i) for i,c in enumerate(tokenize_lines(text),start=1)]


def money(v: Any) -> float:
    return float(Decimal(str(v)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))


def analyze_line(line: dict, catalog: list[dict] = None, markup: float = 0.225) -> dict:
    """Safe quote gate: missing/ambiguous critical fields never become a fabricated match.
    
    Now integrates database loaders for full catalog and compliance checking.
    """
    # Load full catalog from database if not provided; fall back to seeded demo SKUs
    if catalog is None:
        try:
            catalog = database.load_catalog()
        except Exception:
            catalog = sample_catalog()
        if not catalog:
            catalog = sample_catalog()
    
    line = dict(line)
    
    # Normalize synonyms if not already done
    if line.get('raw_text') and not line.get('normalized_text'):
        line['normalized_text'] = normalize_synonym(line['raw_text'])
    
    # Check compliance triggers
    if not line.get('compliance_triggers'):
        line['compliance_triggers'] = check_compliance_triggers(line.get('normalized_text', line.get('raw_text', '')))
    
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
    
    def _norm_mat(v: str) -> str:
        return (v or '').lower().replace('_', ' ').strip()

    line_material_cmp = _norm_mat(line.get('material', ''))
    line_form_cmp = _norm_mat(line.get('form', ''))
    line_finish = (line.get('finish') or '').upper().strip()
    line_grade = (line.get('grade') or '').lower().strip()
    
    candidates = []
    for item in catalog:
        cat_material = _norm_mat(item.get('material_family') or item.get('material') or '')
        cat_form = _norm_mat(item.get('form') or '')
        cat_grade = (item.get('grade') or '').lower().strip()
        cat_finish = (item.get('finish') or '').upper().strip()
        
        if cat_material and line_material_cmp and cat_material != line_material_cmp:
            continue
        if cat_form and line_form_cmp and cat_form != line_form_cmp:
            continue
        if cat_grade and line_grade and cat_grade != line_grade:
            continue
        if line_finish and cat_finish and cat_finish != line_finish:
            continue
        
        cat_thickness = float(item.get('thickness_in', 0)) if item.get('thickness_in') else None
        line_thickness = float(line.get('thickness_in')) if line.get('thickness_in') else None
        if cat_thickness is not None and line_thickness is not None:
            if abs(cat_thickness - line_thickness) > 0.003:
                continue
        elif cat_thickness is None or line_thickness is None:
            continue
        
        cat_width = float(item.get('width_in', 0)) if item.get('width_in') else None
        cat_length = float(item.get('length_in', 0)) if item.get('length_in') else None
        line_width = float(line.get('width_in')) if line.get('width_in') else None
        line_length = float(line.get('length_in')) if line.get('length_in') else None
        if cat_width and cat_length and line_width and line_length:
            if sorted([cat_width, cat_length]) != sorted([line_width, line_length]):
                continue
        elif (cat_width is None or cat_length is None) and (line_width is not None or line_length is not None):
            continue
        
        if line.get('standard_required'):
            cat_standard = (item.get('standard') or '').replace(' ', '')
            if line['standard_required'].replace(' ', '') not in cat_standard.replace(' ', ''):
                continue
        
        candidates.append(item)
    
    # Apply compliance rules when the demo rule table is available
    if candidates and line.get('compliance_triggers'):
        try:
            compliance_result = apply_compliance_rules(line, candidates)
        except Exception:
            compliance_result = {'passed': candidates, 'blocked': [], 'warnings': []}
        if compliance_result['blocked']:
            line['compliance_blocked_skus'] = [sku for sku, _ in compliance_result['blocked']]
            line['compliance_block_reasons'] = dict(compliance_result['blocked'])
            candidates = compliance_result['passed']
        if compliance_result['warnings']:
            line['compliance_warnings'] = dict(compliance_result['warnings'])
    
    line['match_candidates'] = [it['sku'] for it in candidates]
    if len(candidates) == 0:
        line['status'] = 'needs_clarification'
        line['blockers'] = ['no verified compatible catalog SKU']
        line['clarifications'] = [{"field":"sku","question":"Can you confirm your required specifications or preferred product SKU?"}]
        line['approval_status'] = 'pending'
        return line
    elif len(candidates) > 1:
        def _cost(c):
            return _parse_price(c.get('supplier_cost_usd', c.get('unit_price', 0)))
        us_candidates = [c for c in candidates if (c.get('country_of_origin') or '').upper() == 'US']
        pool = us_candidates or candidates
        candidates = sorted(pool, key=_cost)[:1]
    
    it = candidates[0]
    cat_thickness = float(it.get('thickness_in', 0)) if it.get('thickness_in') else 0
    line_thickness = float(line.get('thickness_in')) if line.get('thickness_in') else 0
    thickness_delta = abs(cat_thickness - line_thickness)
    
    line['match'] = {
        'sku': it['sku'],
        'supplier': it.get('supplier') or it.get('mill') or 'Unknown Supplier',
        'matched_grade': it.get('grade'),
        'supplier_standard': it.get('standard'),
        'thickness_tolerance_in': 0.003,
        'thickness_difference_in': round(thickness_delta, 6),
        'reason': 'Grade, material, form and dimensions match; thickness is within the declared 0.003-in tolerance.'
    }
    
    # Dataset SKUs carry `unit_price`; seeded SKUs carry `supplier_cost_usd` / `benchmark_usd`.
    supplier_cost = _parse_price(it.get('unit_price') or it.get('supplier_cost_usd') or 0)
    unit = money(supplier_cost * (1 + markup))
    try:
        benchmark_record = database.find_benchmark(it.get('benchmark_id')) if it.get('benchmark_id') else None
    except Exception:
        benchmark_record = None
    if benchmark_record:
        bench = money(float(benchmark_record.get('median_per_lb', 0)))
        bench_source = benchmark_record.get('basis') or 'N/A'
        bench_as_of = benchmark_record.get('as_of') or '2026-10-10'
    elif it.get('benchmark_usd') is not None:
        bench = money(float(it['benchmark_usd']))
        bench_source = it.get('benchmark_source') or 'N/A'
        bench_as_of = it.get('benchmark_as_of') or '2026-10-10'
    else:
        bench = None
        bench_source = 'N/A'
        bench_as_of = '2026-10-10'
    
    line['pricing'] = {
        'supplier_cost_usd': supplier_cost,
        'markup_pct': money(markup*100),
        'unit_price_usd': unit,
        'quantity': line['quantity'],
        'line_total_usd': money(unit*line['quantity']),
        'benchmark_unit_usd': bench,
        'benchmark_source': bench_source,
        'benchmark_as_of': bench_as_of,
        'below_benchmark_pct': money(((bench-unit)/bench)*100) if bench and bench > 0 else None,
        'explanation': (
            f'Cost ${supplier_cost:.2f} × (1 + {markup*100:g}% markup) = ${unit:.2f}'
            + (f'; compared with a synthetic demo benchmark of ${bench:.2f}.' if bench else '.')
        ),
        'data_is_synthetic': True,
    }

    certs_available = list(it.get('certificate_types') or [])
    if isinstance(it.get('certifications'), str) and it.get('certifications'):
        certs_available = [c.strip() for c in it['certifications'].split(',') if c.strip()]
    docs_verified = bool(it.get('documents_verified')) or str(it.get('mtr_available', '')).upper() in ('Y', 'TRUE', '1')
    # Demo catalog marks mill-test availability via mtr_available=Y rather than a cert token.
    if docs_verified or str(it.get('mtr_available', '')).upper() in ('Y', 'TRUE', '1'):
        certs_available = list(certs_available) + ['MTR']

    issues = []
    certs_upper = {str(c).upper() for c in certs_available}
    required_certs = line.get('required_certificates', [])
    for cert in required_certs:
        if str(cert).upper() not in certs_upper:
            issues.append(f'{cert} is not listed by supplier')
        elif not docs_verified:
            issues.append(f'{cert} document not verified')
    
    if line.get('country_of_origin_required'):
        coo = it.get('country_of_origin')
        com = it.get('country_of_melt')
        if not coo:
            issues.append('Country of origin evidence unavailable')
        elif line.get('compliance_triggers', {}).get('buy_america'):
            if str(coo).upper() != 'US':
                issues.append(f'Country of origin is {coo}, does not meet Buy America requirement')
            if com and str(com).upper() != 'US':
                issues.append(f'Country of melt is {com}, may not meet Buy America requirement')
    
    line['compliance'] = {
        'status': 'pass' if not issues else 'blocked',
        'issues': issues,
        'available_certificates': list(certs_available),
        'documents_verified': docs_verified,
        'country_of_origin': it.get('country_of_origin'),
        'country_of_melt': it.get('country_of_melt'),
        'supplier_standard': it.get('standard'),
        'note': 'Document verification and standards are supplier-record assertions, not an independently performed inspection.'
    }
    line['blockers'] = issues
    line['clarifications'] = []
    line['status'] = 'blocked_compliance' if issues else ('approved' if line.get('approval_status')=='approved' else 'ready_for_approval')
    if issues:
        line['approval_status'] = 'pending'
    return line


def _parse_price(value: Any) -> float:
    """Parse price value, handling strings and None."""
    if value is None or value == '':
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


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


def normalize_synonym(text: str) -> str:
    """Apply synonym mapping to normalize RFQ text.
    
    Converts buyer shorthand (e.g., 'SS', 'galv', '#4') to canonical forms
    using the synonyms table from the database when available.
    """
    try:
        synonyms = database.load_synonyms()
    except Exception:
        return text
    normalized = text
    for term, canonical in synonyms.items():
        pattern = r'\b' + re.escape(term) + r'\b'
        normalized = re.sub(pattern, canonical, normalized, flags=re.IGNORECASE)
    return normalized


def resolve_gauge_to_thickness(gauge: str, material: str, form: str = "sheet") -> dict:
    """Resolve gauge notation to thickness using material-specific lookup tables.
    
    Args:
        gauge: Gauge number (e.g., "16", "18", "14")
        material: Material family (e.g., "stainless_steel", "galvanized_steel", "carbon_steel")
        form: Product form ("sheet" or "tube"). Tube has different gauge standards.
    
    Returns:
        Dict with keys:
            - thickness_in: Resolved thickness in inches, or None if unknown
            - assumption: Description of applied assumption (e.g., "tube 16 ga = 0.065 in wall")
            - lookup_table: Which table was used ("gauge_table" or "tube_wall_gauge")
    """
    result = {
        'thickness_in': None,
        'assumption': None,
        'lookup_table': None,
    }
    
    # Normalize material family
    material_lower = (material or "").lower()
    if 'stainless' in material_lower:
        material_key = 'stainless'
    elif 'galvanized' in material_lower or 'galv' in material_lower:
        material_key = 'galvanized'
    elif 'carbon' in material_lower:
        material_key = 'carbon_steel'
    elif 'aluminum' in material_lower or 'alum' in material_lower:
        material_key = 'aluminum'
    else:
        material_key = 'stainless'  # Default fallback
    
    # Check tube gauge first (if form indicates tube)
    if form and 'tube' in form.lower():
        try:
            tube_gauges = database.load_tube_gauge()
        except Exception:
            tube_gauges = {'16': 0.065, '14': 0.083, '18': 0.049}
        if gauge in tube_gauges:
            thickness = tube_gauges[gauge]
            result['thickness_in'] = thickness
            result['assumption'] = f"tube {gauge} ga wall thickness = {thickness:.3f}\" (from tube_wall_gauge table)"
            result['lookup_table'] = 'tube_wall_gauge'
            return result
    
    # Otherwise use standard gauge table (material-specific)
    try:
        gauge_tables = database.load_gauge_tables()
    except Exception:
        gauge_tables = {}
    if gauge in gauge_tables:
        thickness = gauge_tables[gauge].get(material_key)
        if thickness is not None:
            result['thickness_in'] = thickness
            result['assumption'] = f"{material_key} {gauge} ga = {thickness:.4f}\" (from gauge_table)"
            result['lookup_table'] = 'gauge_table'
            return result

    # Seeded fallback when demo DB tables are unavailable (hackathon local / tests)
    fallback = {
        'stainless': {'16': 0.0625, '18': 0.0500, '14': 0.078125},
        'galvanized': {'16': 0.0635, '18': 0.0516, '14': 0.0785},
        'carbon_steel': {'16': 0.0598, '18': 0.0478, '14': 0.0747},
        'aluminum': {'16': 0.0508, '18': 0.0403, '14': 0.0641},
    }.get(material_key, {})
    if gauge in fallback:
        thickness = fallback[gauge]
        result['thickness_in'] = thickness
        result['assumption'] = f"{material_key} {gauge} ga = {thickness:.4f}\" (seeded fallback)"
        result['lookup_table'] = 'seeded_fallback'
        return result
    
    # No resolution found
    result['assumption'] = f"gauge {gauge} not found for {material_key} in lookup tables"
    return result


def check_compliance_triggers(raw_text: str) -> dict:
    """Detect compliance requirements mentioned in RFQ text.
    
    Scans the RFQ for triggers like 'buy america', 'dfars', 'mtr', etc.
    
    Returns:
        Dict with keys:
            - buy_america: bool, requirement detected
            - dfars: bool, requirement detected
            - mtr: bool, requirement detected (mill test report)
            - leed: bool, requirement detected
            - aama: bool, AAMA 611 standard mentioned
            - other_standards: list of detected standards
            - coo_required: Country of origin required
    """
    text_lower = raw_text.lower()
    
    return {
        'buy_america': bool(re.search(r'\b(buy america|usa origin|domestic only|us origin|made in usa)\b', text_lower)),
        'dfars': bool(re.search(r'\b(dfars|specialty metals|foreign origin alert|foa)\b', text_lower)),
        'mtr': bool(re.search(r'\b(mtr|mill test report|mill test cert|mill cert)\b', text_lower)),
        'leed': bool(re.search(r'\bleed\b', text_lower)),
        'aama': bool(re.search(r'\baama\s*611\b', text_lower)),
        'other_standards': re.findall(r'\b(ASTM\s+[A-Z]\d+(?:\s*/\s*[A-Z]\d+)?)\b', raw_text, re.I),
        'coo_required': bool(re.search(r'\b(country of origin|coo)\b', text_lower)),
    }


def apply_compliance_rules(line: dict, candidates: list[dict]) -> dict:
    """Filter and validate candidates against compliance rules.
    
    Applies all rules from compliance_rules table and returns filtered results
    with compliance annotations.
    
    Args:
        line: Normalized line extract with compliance triggers
        candidates: List of catalog SKU candidates
        
    Returns:
        Dict with keys:
            - passed: List of SKUs that passed all rules
            - blocked: List of (SKU, reason) tuples for SKUs that failed BLOCK rules
            - warnings: List of (SKU, reason) tuples for SKUs that failed WARN rules
            - compliance_status: Overall status (OK, WARN, BLOCK)
    """
    try:
        rules = database.load_compliance_rules()
    except Exception:
        return {'passed': list(candidates), 'blocked': [], 'warnings': [], 'compliance_status': 'OK'}
    compliance_triggers = line.get('compliance_triggers', {})
    
    passed = []
    blocked = []
    warnings = []
    
    for sku_item in candidates:
        sku_blocked = False
        sku_warnings = []
        
        for rule in rules:
            rule_id = rule['rule_id']
            trigger_pattern = rule['trigger_in_rfq']
            requirement = rule['requirement']
            catalog_field = rule['catalog_field']
            pass_condition = rule['pass_condition']
            on_fail = rule['on_fail']
            
            # Check if this rule's trigger applies to this line
            trigger_matched = False
            for trigger in trigger_pattern.split('|'):
                trigger = trigger.strip()
                if trigger and re.search(r'\b' + re.escape(trigger) + r'\b', 
                                        ' '.join([str(v) for v in compliance_triggers.values()]), 
                                        re.I):
                    trigger_matched = True
                    break
            
            if not trigger_matched:
                continue
            
            # Get the field value from the SKU
            field_value = str(sku_item.get(catalog_field, '')).upper()
            
            # Check if it meets the pass condition
            condition_passes = field_value == pass_condition.upper()
            
            if not condition_passes:
                reason = f"{rule_id}: SKU {sku_item['sku']} has {catalog_field}={field_value}, required {pass_condition}"
                if on_fail == 'BLOCK':
                    sku_blocked = True
                    blocked.append((sku_item['sku'], reason))
                elif on_fail == 'WARN':
                    sku_warnings.append(reason)
        
        if not sku_blocked:
            if sku_warnings:
                warnings.append((sku_item['sku'], '; '.join(sku_warnings)))
            else:
                passed.append(sku_item)
    
    compliance_status = 'BLOCK' if blocked else ('WARN' if warnings else 'OK')
    
    return {
        'passed': passed,
        'blocked': blocked,
        'warnings': warnings,
        'compliance_status': compliance_status,
    }


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
