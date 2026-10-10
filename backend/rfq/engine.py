"""Matching, clarification, compliance, selection and pricing for one parsed line.

All deterministic and data-driven (catalog, benchmarks, compliance rules from the dataset).
"""
from __future__ import annotations

import re

from .parse import ft_to_lengths
from .refdata import ref

SEVERITY = {"OK": 0, "INFO": 0, "WARN": 1, "BLOCK": 2}
STEEL = {"stainless steel", "carbon steel", "galvanized steel"}
ATTR_LABEL = {"grade": "grade/alloy", "temper": "temper", "finish": "finish", "thickness_in": "thickness",
              "size": "sheet size", "width_in": "width", "height_in": "height", "length_in": "length"}
FLAT = {"sheet", "plate", "tread plate"}


# ---------- RFQ-level requirements ----------
def detect_requirements(text: str) -> dict:
    t = text.lower()
    req: dict[str, dict] = {}
    def add(key, why, **kw):
        req[key] = {"source": why, **kw}
    if re.search(r"\bmtrs?\b|mill (test|cert)|test reports?", t):
        scope = "stainless steel" if re.search(r"(on|for) all stainless", t) else "all"
        add("mtr", "RFQ asks for mill test reports", scope=scope, strict=not re.search(r"where available", t))
    if re.search(r"en\s*10204\s*3\.1|3\.1 cert", t):
        add("en10204_31", "RFQ asks for EN 10204 3.1 certificates")
    if re.search(r"buy america|49 cfr 661|\bbaba\b|\bfta\b", t) and not re.search(r"no buy america", t):
        add("buy_america", "Buy America applies (domestic melt and manufacture)")
    if re.search(r"\bdfars\b", t):
        add("dfars", "DFARS specialty metals")
    if re.search(r"country of origin|\bcoo\b", t):
        add("coo", "Country of origin must be stated per line")
    if re.search(r"domestic preferred", t):
        add("domestic_pref", "Buyer prefers domestic material")
    if re.search(r"aama\s*611", t):
        add("aama611", "Anodized finishes must be AAMA 611 certified")
    if re.search(r"\bleed\b|recycled content", t):
        add("leed", "Recycled content documentation (LEED)")
    if re.search(r"do not substitute|no substitut|substitutions require", t):
        add("no_substitution", "No substitutions of alloys or grades")
    return req


# ---------- matching ----------
def _close(a, b, tol_abs, tol_rel=0.0):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(tol_abs, tol_rel * abs(b))


def _finish_ok(want: str, have: str) -> bool:
    if want == have:
        return True
    return want == "mill" and have.startswith("mill")


def compatible(spec: dict, item: dict, relax: set[str] = frozenset()) -> bool:
    fam = spec["material_family"]
    if fam and item.get("material_family") != fam:
        return False
    if spec["grade"] and "grade" not in relax and item.get("grade") != spec["grade"]:
        return False
    if spec["temper"] and item.get("temper") and item["temper"].upper() != spec["temper"].upper():
        return False
    if spec["shape"] and item.get("shape") != spec["shape"]:
        return False
    if spec["finish"] and "finish" not in relax and not _finish_ok(spec["finish"], item.get("finish") or ""):
        return False
    if spec["thickness_in"] is not None and not _close(spec["thickness_in"], item.get("thickness_in"), 0.0025, 0.03):
        return False
    for k in ("width_in", "height_in", "length_in"):
        if spec[k] is not None and not _close(spec[k], item.get(k), 0.05):
            return False
    return True


def _value(item, attr):
    if attr == "size":
        return (item.get("width_in"), item.get("length_in"))
    return item.get(attr)


def _fmt(attr, v) -> str:
    if v in (None, ""):
        return "n/a"
    if attr == "size":
        return f"{v[0]:g} x {v[1]:g} in"
    if attr in ("thickness_in", "width_in", "height_in"):
        return f"{v:g} in"
    if attr == "length_in":
        return f"{v / 12:g} ft"
    return str(v)


def unspecified_attrs(spec: dict) -> list[str]:
    attrs = ["grade", "temper", "finish", "thickness_in"]
    if spec["shape"] in FLAT or spec["shape"] is None:
        if spec["width_in"] is None and spec["length_in"] is None:
            attrs.append("size")
    else:
        attrs += [a for a in ("width_in", "height_in", "length_in") if spec[a] is None]
    return [a for a in attrs if a == "size" or spec.get(a) in (None, "")]


def describe_spec(spec: dict) -> str:
    parts = []
    if spec.get("grade"):
        parts.append(spec["grade"] + (f"-{spec['temper']}" if spec.get("temper") else ""))
    elif spec.get("material_family"):
        parts.append(spec["material_family"])
    if spec.get("shape"):
        parts.append(spec["shape"])
    if spec.get("finish"):
        parts.append(spec["finish"])
    if spec.get("gauge"):
        parts.append(f"{spec['gauge']} ga")
    elif spec.get("thickness_in"):
        parts.append(f"{spec['thickness_in']:g} in")
    if spec.get("od_in"):
        parts.append(f"{spec['od_in']:g} OD")
    if spec.get("width_in") and spec.get("length_in") and spec.get("shape") in FLAT | {None}:
        parts.append(f"{spec['width_in']:g} x {spec['length_in']:g}")
    elif spec.get("width_in") and spec.get("height_in"):
        parts.append(f"{spec['width_in']:g} x {spec['height_in']:g}")
    elif spec.get("width_in") and spec.get("shape") == "flat bar":
        parts.append(f"x {spec['width_in']:g}")
    if spec.get("length_in") and spec.get("shape") not in FLAT | {None}:
        parts.append(f"{spec['length_in'] / 12:g} ft")
    return " ".join(parts)


# ---------- compliance ----------
def compliance_flags(item: dict, line: dict, req: dict) -> list[dict]:
    flags = []
    fam = item["material_family"]
    def flag(rule, sev, msg):
        flags.append({"rule_id": rule, "severity": sev, "message": msg})
    if "mtr" in req and (req["mtr"]["scope"] == "all" or req["mtr"]["scope"] == fam):
        if item.get("mtr_available") == "Y":
            flag("CR-01", "OK", f"MTR available ({item.get('mtr_type') or 'mill cert'})")
        else:
            flag("CR-01", "WARN", "No MTR available for this SKU (commercial quality); ask buyer to accept a C of C")
    if "en10204_31" in req and item.get("mtr_type") != "EN 10204 3.1":
        flag("CR-02", "WARN", "EN 10204 3.1 certificate not available")
    if "buy_america" in req and fam in STEEL:
        if item.get("buy_america_compliant") == "Y":
            flag("CR-03", "OK", "Buy America: US melted and manufactured")
        elif item.get("country_of_origin") == "US":
            flag("CR-03", "BLOCK", f"Buy America FAILS: origin US but melted in {item.get('country_of_melt')}")
        else:
            flag("CR-03", "BLOCK", f"Buy America FAILS: origin {item.get('country_of_origin')}, melt {item.get('country_of_melt')}")
    if "dfars" in req and fam in STEEL and item.get("dfars_compliant") != "Y":
        flag("CR-04", "BLOCK", "Not DFARS compliant")
    if "coo" in req:
        coo = item.get("country_of_origin")
        if not coo:
            flag("CR-05", "WARN", "Country of origin unknown")
        elif coo != "US":
            flag("CR-05", "WARN", f"State country of origin on the quote: {coo}")
        else:
            flag("CR-05", "OK", "Country of origin: US")
    if "domestic_pref" in req and item.get("country_of_origin") != "US":
        flag("CR-06", "WARN", f"Domestic preferred; this SKU is {item.get('country_of_origin')}")
    if "aama611" in req and "anod" in (item.get("finish") or ""):
        if "AAMA 611" in (item.get("certifications") or ""):
            flag("CR-07", "OK", "AAMA 611 certified")
        else:
            flag("CR-07", "BLOCK", "Anodized finish is not AAMA 611 certified")
    if "leed" in req:
        if item.get("recycled_content_pct") in (None, ""):
            flag("CR-08", "WARN", "No recycled-content documentation for LEED")
        else:
            flag("CR-08", "OK", f"Recycled content documented: {item['recycled_content_pct']:g}%")
    qty = line.get("qty_ea")
    if isinstance(qty, (int, float)) and item.get("stock_qty") is not None and item["stock_qty"] < qty:
        # availability is shown to the buyer but is not a compliance failure on its own
        flag("CR-10", "INFO", f"Only {item['stock_qty']:g} in stock; lead time {item.get('lead_time_days') or 0:g} days for the rest")
    return flags


def worst(flags: list[dict]) -> str:
    sev = max((f["severity"] for f in flags), key=lambda s: SEVERITY[s], default="OK")
    return "OK" if sev == "INFO" else sev


# ---------- pricing ----------
def unit_price(item: dict, qty) -> tuple[float, str]:
    q = qty or 0
    if q >= 50 and item.get("unit_price_qty50"):
        return item["unit_price_qty50"], "qty 50+ price (-9%)"
    if q >= 10 and item.get("unit_price_qty10"):
        return item["unit_price_qty10"], "qty 10+ price (-5%)"
    return item.get("unit_price") or 0.0, "list price"


def price_line(item: dict, qty) -> dict | None:
    if not item.get("unit_price"):
        return None
    unit, tier = unit_price(item, qty)
    weight = item.get("weight_lb_each") or 0
    per_lb = unit / weight if weight else None
    bm = ref().benchmarks.get(item.get("benchmark_id"))
    out = {"unit_price": round(unit, 2), "extended": round(unit * qty, 2) if isinstance(qty, (int, float)) else None,
           "tier": tier, "weight_lb_each": weight, "price_per_lb": round(per_lb, 2) if per_lb else None,
           "benchmark": None, "position": None, "rationale": None}
    if bm and per_lb:
        low, med, high = bm["low_per_lb"], bm["median_per_lb"], bm["high_per_lb"]
        vs_med = (per_lb - med) / med * 100
        if per_lb < low:
            pos, text = "below_range", f"below the market low (${low:.2f})"
        elif per_lb <= med:
            pos, text = "below_median", f"{abs(vs_med):.0f}% under the market median"
        elif per_lb <= high:
            pos, text = "above_median", f"{vs_med:.0f}% over the median, still inside the market range"
        else:
            pos, text = "above_range", f"ABOVE the market high (${high:.2f}/lb) by {(per_lb - high) / high * 100:.0f}%; say so to the buyer"
        out["benchmark"] = {"id": bm["benchmark_id"], "low": low, "median": med, "high": high, "basis": bm["basis"],
                            "as_of": bm["as_of"], "source": bm["source"]}
        out["position"] = pos
        out["rationale"] = (f"${per_lb:.2f}/lb vs market ${low:.2f}-${high:.2f}/lb (median ${med:.2f}) for "
                            f"{bm['grade']} {bm['form']} {bm['finish_class']}: {text}. {tier.capitalize()}.")
    return out


# ---------- one line, end to end ----------
def _question_options(attr, values, items) -> list[str]:
    opts = []
    for v in values:
        label = _fmt(attr, v)
        stock = sum((i.get("stock_qty") or 0) for i in items if _value(i, attr) == v)
        opts.append(f"{label} ({stock:g} in stock)" if attr == "length_in" else label)
    return opts


def evaluate(line: dict, catalog: list[dict], req: dict) -> dict:
    """Fill status, candidates, selection, price, compliance and question on a parsed line (in place)."""
    spec = line["spec"]
    n = line["line_no"]
    for k in ("question", "options", "selected_sku", "selection_reason", "item", "price"):
        line[k] = None
    line["candidates"], line["alternatives"], line["clarify_fields"] = [], [], []
    line["compliance"] = {"result": "n/a", "flags": []}
    line["assumptions"] = list(line.get("parse_assumptions", []))
    line["qty_ea"] = line.get("qty")
    desc = describe_spec(spec) or line["raw"]

    if not spec["material_family"]:
        line["status"] = "CLARIFY"
        line["clarify_fields"] = ["material"]
        line["question"] = f"Line {n} (\"{line['raw']}\"): what material and grade do you need?"
        return line

    cands = [i for i in catalog if compatible(spec, i)]
    if not cands:
        line["status"] = "NO_MATCH"
        alts = [i for i in catalog if compatible(spec, i, relax={"grade"})] if spec["grade"] else []
        if alts:
            alt = alts[0]
            line["alternatives"] = [{"sku": a["sku"], "description": a["description"]} for a in alts[:3]]
            nosub = " The RFQ says not to substitute grades, so we need your approval." if "no_substitution" in req else ""
            line["question"] = (f"We don't stock {desc} in {spec['grade']}. We do stock it in {alt['grade']} "
                                f"({alt['sku']}). Is {alt['grade']} acceptable, or should we source {spec['grade']}?{nosub}")
        else:
            line["question"] = f"We don't stock {desc}. Should we source it (lead time TBD) or remove the line from the quote?"
        return line

    line["candidates"] = [c["sku"] for c in cands]
    varying = []
    for attr in unspecified_attrs(spec):
        vals = sorted({_value(c, attr) for c in cands}, key=lambda v: (str(type(v)), v if v is not None else ""))
        if len(vals) > 1:
            varying.append((attr, vals))
    qty_missing = line.get("qty") is None

    if varying or qty_missing:
        line["status"] = "CLARIFY"
        parts, opts = [], []
        for attr, vals in varying:
            o = _question_options(attr, vals, cands)
            opts.append({"field": attr, "choices": o})
            parts.append(f"{ATTR_LABEL[attr]} ({', '.join(o)})")
        if qty_missing:
            parts.append("quantity")
            opts.append({"field": "qty", "choices": []})
        line["clarify_fields"] = [o["field"] for o in opts]
        line["options"] = opts
        what = f"{line['qty']:g} x " if line.get("qty") else ""
        line["question"] = f"For line {n} ({what}{desc}): which {'; '.join(parts)} do you need?"
        return line

    # single-valued attributes the buyer left out
    assumed = []
    for attr in unspecified_attrs(spec):
        v = _value(cands[0], attr)
        if v in (None, ""):
            continue
        if attr == "grade":
            spec["grade"] = v
            if spec["material_family"] == "aluminum" or spec["material_family"] == "carbon steel":
                assumed.append(f"alloy/grade {v}")
        elif attr == "temper":
            spec["temper"] = v
            if spec["shape"] != "tread plate":
                assumed.append(f"temper {v}")
        elif attr == "finish":
            spec["finish"] = v
        elif attr == "size":
            spec["width_in"], spec["length_in"] = v
        else:
            spec[attr] = v
    if assumed:
        line["assumptions"].append(f"Not stated: {', '.join(assumed)}. That is the only stocked option for this item.")
    spec["standard"] = spec["standard"] or cands[0].get("standard")

    # feet -> stock lengths
    if (line.get("uom") or "").lower() == "ft" and isinstance(line.get("qty"), (int, float)):
        L = cands[0].get("length_in")
        if L:
            ea = ft_to_lengths(line["qty"], L)
            line["qty_ea"] = ea
            line["assumptions"].append(f"{line['qty']:g} ft ordered = {ea} x {L / 12:g} ft stock lengths")

    line["status"] = "MATCH_ASSUMPTION" if line["assumptions"] else "MATCH"

    # choose among eligible SKUs (usually the same product from different mills / origins)
    scored = []
    for c in cands:
        flags = compliance_flags(c, line, req)
        price, _ = unit_price(c, line["qty_ea"])
        short = 1 if (c.get("stock_qty") or 0) < (line["qty_ea"] or 0) else 0
        scored.append((SEVERITY[worst(flags)], short, price, c, flags))
    cheapest = min(s[2] for s in scored)
    def key(s):
        dom = 0
        if "domestic_pref" in req:
            dom = 0 if (s[3].get("country_of_origin") == "US" and s[2] <= cheapest * 1.10) else 1
        return (s[0], dom, s[1], s[2])
    scored.sort(key=key)
    best = scored[0]
    item, flags = best[3], best[4]
    line["selected_sku"] = item["sku"]
    line["item"] = {k: item.get(k) for k in ("sku", "description", "standard", "dual_cert", "mill", "country_of_origin",
                                               "country_of_melt", "stock_qty", "lead_time_days", "certifications", "mtr_type")}
    line["price"] = price_line(item, line["qty_ea"])
    line["compliance"] = {"result": worst(flags), "flags": flags}
    line["alternatives"] = [{"sku": s[3]["sku"], "unit_price": s[2], "origin": s[3].get("country_of_origin"),
                             "compliance": worst(s[4]), "stock_qty": s[3].get("stock_qty")} for s in scored[1:]]
    if len(scored) > 1:
        reasons = []
        for s in scored[1:]:
            o = s[3]
            if s[0] > best[0]:
                why = next((f["message"] for f in s[4] if f["severity"] != "OK"), "compliance")
                reasons.append(f"{o['sku']} rejected: {why}")
            elif s[2] < best[2]:
                reasons.append(f"{o['sku']} is ${best[2] - s[2]:.2f} cheaper but {('domestic material is preferred' if 'domestic_pref' in req else 'has less stock')}")
            else:
                reasons.append(f"{o['sku']} costs ${s[2] - best[2]:.2f} more")
        line["selection_reason"] = f"Chose {item['sku']} ({item.get('country_of_origin')}). " + "; ".join(reasons) + "."
    else:
        line["selection_reason"] = f"{item['sku']} is the only stocked SKU for this spec."
    if line["compliance"]["result"] == "BLOCK":
        dom = [s for s in scored if s[0] < SEVERITY["BLOCK"]]
        line["question"] = (f"Line {n} ({desc}) can't be quoted as compliant: "
                            + next(f["message"] for f in flags if f["severity"] == "BLOCK")
                            + ". We have no compliant stock for it. Do you want us to source domestic material, or quote it as non-compliant?")
    return line
