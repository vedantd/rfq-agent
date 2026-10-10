"""Rule-based line parser: messy RFQ text -> normalized spec.

Deterministic on purpose. The LLM (when enabled) helps phrase questions and read buyer answers,
but the numbers (gauge tables, unit conversions) never depend on a model.
"""
from __future__ import annotations

import math
import re

from .refdata import ref

NUM = r"(?:\d+-\d+/\d+|\d+/\d+|\d*\.\d+|\d+)"
STD_SIZES = [36, 48, 60, 72, 96, 120, 144]
LONG_SHAPES = {"round tube", "square tube", "rect tube", "angle", "channel", "flat bar", "HSS square"}
SECTION_SHAPES = {"square tube", "rect tube", "angle", "channel", "HSS square"}
FLAT_SHAPES = {"sheet", "plate", "tread plate"}


def to_float(tok: str) -> float:
    tok = tok.strip().strip('"').strip()
    m = re.fullmatch(r"(\d+)-(\d+)/(\d+)", tok)
    if m:
        return int(m[1]) + int(m[2]) / int(m[3])
    m = re.fullmatch(r"(\d+)/(\d+)", tok)
    if m:
        return int(m[1]) / int(m[2])
    return float(tok)


def _snap_size(inches: float) -> float:
    best = min(STD_SIZES, key=lambda s: abs(s - inches))
    return float(best) if abs(best - inches) / best < 0.03 else round(inches, 2)


def empty_spec() -> dict:
    return {
        "material_family": None, "grade": None, "temper": None, "shape": None, "finish": None,
        "thickness_in": None, "gauge": None, "width_in": None, "height_in": None, "length_in": None,
        "od_in": None, "standard": None,
    }


def _material_and_grade(tl: str, spec: dict, notes: list):
    fam = grade = temper = None
    if re.search(r"\bbrass\b|\bc2[0-9]{2}\b", tl):
        fam = "brass"
        m = re.search(r"\b(c2[0-9]{2})\b", tl)
        grade = m[1].upper() if m else None
    elif re.search(r"duplex|\b2205\b", tl):
        fam, grade = "stainless steel", "2205"
    elif re.search(r"\bgalv|\bhdg\b|\bg90\b|\bg60\b", tl):
        fam, grade = "galvanized steel", "CS Type B"
    elif re.search(r"stainless|\bss\b|\bs/s\b|\bsst\b|ss3[01]\d|(?<![\d.])(t|type\s*)?3[01][46]l?\b", tl):
        fam = "stainless steel"
    elif re.search(r"\balum|\b(3003|5052|5005|6061|6063)\b", tl):
        fam = "aluminum"
    elif re.search(r"\ba36\b|\bhr\b|\bhss\b|\bms\b|\bcs\b|\ba500\b|\bblack\b|\bmild steel\b|\bcarbon\b", tl):
        fam = "carbon steel"

    m = re.search(r"(?<![\d.])(304|316|3003|5052|5005|6061|6063)(l?)(?:-?(h\d\d|t\d{1,3}))?(?!\d)", tl)
    if m and grade is None:
        grade = m[1]
        if m[2]:
            notes.append(f"{m[1]}L requested; covered by stocked dual-cert {m[1]}/{m[1]}L")
        if m[3]:
            temper = m[3].upper()
        if fam is None:
            fam = "aluminum" if m[1] in ("3003", "5052", "5005", "6061", "6063") else "stainless steel"
    if fam == "aluminum" and temper is None:
        m = re.search(r"\b(h\d\d|t\d{1,3})\b", tl)
        if m:
            temper = m[1].upper()
    if fam == "carbon steel" and grade is None:
        if re.search(r"\ba500\b|\bhss\b", tl):
            grade = "A500 Gr B/C"
        elif re.search(r"\ba36\b", tl):
            grade = "A36"
    spec.update(material_family=fam, grade=grade, temper=temper)


def _shape(tl: str) -> str | None:
    if re.search(r"diamond|tread|checker", tl):
        return "tread plate"
    if re.search(r"\bhss\b", tl):
        return "HSS square"
    if re.search(r"rect\w*\.?\s+tub", tl):
        return "rect tube"
    if re.search(r"\b(sq|square)\w*\.?\s+tub", tl):
        return "square tube"
    if re.search(r"\btub(e|es|ing)\b|\bpipe\b|\bod\b", tl):
        return "round tube"
    if re.search(r"flat\s*bar|\bfb\b", tl):
        return "flat bar"
    if re.search(r"\bangle\b|(?<![a-z0-9])l\s?\d", tl):
        return "angle"
    if re.search(r"\bchannel\b", tl):
        return "channel"
    if re.search(r"\bplate\b|\bplt\b|\bpl\b", tl):
        return "plate"
    if re.search(r"\bsheets?\b|\bsht\b|\bsh\b", tl):
        return "sheet"
    return None


def _finish(tl: str, fam: str | None) -> str | None:
    if re.search(r"#\s?8\b|mirror", tl):
        return "#8"
    if re.search(r"#\s?4|no\.?\s?4\b|brushed|satin|polished", tl):
        return "#4"
    if re.search(r"\b2b\b", tl):
        return "2B"
    if re.search(r"\bba\b|bright\s+anneal", tl):
        return "BA"
    if re.search(r"clr\.?\s*anod|clear\s*anod", tl):
        return "clear anodized"
    if re.search(r"\bg90\b", tl):
        return "G90"
    if re.search(r"\bg60\b", tl):
        return "G60"
    if re.search(r"\bmill\b", tl):
        return "2B" if fam == "stainless steel" else "mill"
    return None


def parse_line(raw: str, qty_hint=None, uom_hint: str | None = None) -> dict:
    """Parse one RFQ line. qty_hint/uom_hint come from a table column when the source had one."""
    notes: list[str] = []
    assumptions: list[str] = []
    spec = empty_spec()
    tl = " " + raw.lower().replace("″", '"').replace("′", "'").replace("''", '"') + " "

    _material_and_grade(tl, spec, notes)
    fam = spec["material_family"]
    shape = _shape(tl)
    spec["finish"] = _finish(tl, fam)

    s = tl  # working copy; consumed tokens are blanked out
    def eat(m):
        nonlocal s
        s = s[: m.start()] + " " * (m.end() - m.start()) + s[m.end():]

    thickness = gauge = width = height = length = od = None
    metric_thk = None

    # 1. metric sizes and thickness
    m = re.search(r"(\d{3,4})\s*x\s*(\d{3,4})(?!\s*mm\b)?", s)
    if m and int(m[1]) >= 300 and int(m[2]) >= 300:
        w, l = _snap_size(int(m[1]) / 25.4), _snap_size(int(m[2]) / 25.4)
        assumptions.append(f"Metric size {m[1]}x{m[2]} mm read as {w:g} x {l:g} in")
        width, length = w, l
        eat(m)
    m = re.search(rf"({NUM})\s*mm\b", s)
    if m:
        metric_thk = to_float(m[1]) / 25.4
        eat(m)

    # 2. OD (+ optional wall right after)
    m = re.search(rf"({NUM})\s*\"?\s*od\b(?:\s*x\s*({NUM})\s*\"?)?", s)
    if m:
        od = to_float(m[1])
        if m[2]:
            thickness = to_float(m[2])
        eat(m)
        shape = shape or "round tube"

    # 3. ft-in lengths like 24'-0"
    m = re.search(r"(\d+)\s*'\s*-\s*(\d+)\s*\"", s)
    if m:
        length = int(m[1]) * 12 + int(m[2])
        eat(m)

    # 4. three-part dimensions
    m = re.search(rf"({NUM})\s*(\"|'|ft)?\s*x\s*({NUM})\s*(\"|'|ft)?\s*x\s*({NUM})\s*(\"|'|ft)?", s)
    if m:
        a, b, c = to_float(m[1]), to_float(m[3]), to_float(m[5])
        if m[4] == "'" or m[6] == "'" or m[4] == "ft":
            thickness, width, length = a, b * 12, c * 12           # 3/8 x 4' x 8'
        elif a < 1 and b >= 12:
            thickness, width, length = a, b, c                      # .500 x 48 x 144
        else:
            width, height, thickness = a, b, c                      # 2 x 4 x .125 (sections)
        eat(m)

    # 5. two-part dimensions
    if width is None:
        m = re.search(rf"({NUM})\s*(\"|'|ft)?\s*x\s*({NUM})\s*(\"|'|ft)?", s)
        if m:
            a, b = to_float(m[1]), to_float(m[3])
            feet = m[2] == "'" or m[4] == "'"
            if shape == "flat bar":
                thickness, width = min(a, b), max(a, b)
            elif shape in SECTION_SHAPES and not feet:
                width, height = a, b
            elif feet or (a <= 12 and b <= 12):
                width, length = a * 12, b * 12
            else:
                width, length = a, b
            eat(m)

    # 6. gauge
    m = re.search(r"\b(\d{1,2})\s*-?\s*(?:ga|gauge|gage)\b(\s*wall)?", s)
    if not m:
        m = re.search(r"\bss3\d\d-(\d{1,2})-", s)
    if m:
        gauge = int(m[1])
        eat(m)

    # 7. stock length in feet
    if length is None or (shape in LONG_SHAPES and length and length > 200 and False):
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:'|ft\b|feet\b|foot\b)", s)
        if m:
            length = float(m[1]) * 12
            eat(m)
    elif shape in LONG_SHAPES:
        pass

    # 8. remaining explicit thickness (decimal or fraction)
    if thickness is None and metric_thk is None:
        m = re.search(r"(?<![\d/.])(\d*\.\d+|\d+/\d+)\s*(?:\"|in\b|inch\b)?", s)
        if m:
            v = to_float(m[1])
            if v < 1:
                thickness = v
                eat(m)

    # 9. quantity
    qty, uom = None, None
    if qty_hint not in (None, ""):
        try:
            qty = float(qty_hint)
        except (TypeError, ValueError):
            notes.append(f"Quantity given as '{qty_hint}'")
        uom = (uom_hint or "").strip() or None
    else:
        pats = [
            r"^\s*\((\d+)\)",
            r"\bqty\.?\s*:?\s*(\d+)",
            r"(\d+)\s*(?:pcs|pc|pieces|sheets|shts|sht|sh|ea|each|lengths|lgths|sticks|bars)\b",
            r"\bneed\s+(\d+)",
            r"\bx\s*(\d+)\s*[,.]?\s*$",
        ]
        for p in pats:
            m = re.search(p, s)
            if m:
                qty = float(m[1])
                eat(m)
                break
        uom = "EA" if qty is not None else None
    if qty is not None and qty == int(qty):
        qty = int(qty)

    # ---- normalize thickness by material / shape ----
    tables = ref()
    if shape in ("round tube", "square tube", "rect tube") and gauge is not None and thickness is None:
        wall = tables.tube_wall_gauge.get(gauge)
        if wall:
            thickness = wall
            notes.append(f"{gauge} ga tube wall = {wall:.3f} in (tube gauge, not sheet gauge)")
    elif gauge is not None and fam in tables.sheet_gauge:
        thickness = tables.sheet_gauge[fam].get(gauge, thickness)
    if fam == "stainless steel" and shape in (None, "sheet") and gauge is None:
        ss = tables.sheet_gauge["stainless steel"]
        cs = tables.sheet_gauge["carbon steel"]
        cand = thickness if thickness is not None else metric_thk
        if cand is not None:
            hit = next((g for g, v in ss.items() if abs(v - cand) < 0.0001), None)
            cs_hit = next((g for g, v in cs.items() if abs(v - cand) < 0.0001), None)
            if not hit and not cs_hit:
                hit = next((g for g, v in ss.items() if abs(v - cand) < 0.0006), None)
            if hit:
                gauge = hit
            elif cs_hit and cs_hit in ss:
                gauge = cs_hit
                assumptions.append(f'{cand:g}" is the carbon-steel {cs_hit} ga decimal; read as {cs_hit} ga stainless ({ss[cs_hit]:.3f} in)')
                thickness = ss[cs_hit]
            elif abs(cand - 0.125) < 0.0006 and 11 in ss:
                gauge = 11
                assumptions.append(f'1/8" stainless sheet read as 11 ga ({ss[11]:.3f} in) by trade convention')
                thickness = ss[11]
            elif metric_thk is not None:
                g = min(ss, key=lambda k: abs(ss[k] - cand))
                if abs(ss[g] - cand) / ss[g] < 0.03:
                    gauge = g
                    assumptions.append(f"Metric thickness {cand * 25.4:.1f} mm = {cand:.4f} in, read as {g} ga ({ss[g]:.3f} in)")
                    thickness = ss[g]
    if thickness is None and metric_thk is not None:
        thickness = round(metric_thk, 4)
        assumptions.append(f"Metric thickness converted to {thickness:g} in")
    if fam == "galvanized steel" and gauge is None and thickness is not None:
        gv = tables.sheet_gauge["galvanized steel"]
        g = min(gv, key=lambda k: abs(gv[k] - thickness))
        if abs(gv[g] - thickness) < 0.003:
            gauge, thickness = g, gv[g]

    if shape is None and (width or length) and fam in ("stainless steel", "aluminum", "galvanized steel", "carbon steel"):
        shape = "plate" if (thickness or 0) >= 0.1875 and fam != "stainless steel" else "sheet"
    if shape == "round tube" and od is not None:
        width = od
    if fam is None and shape in ("angle", "channel") and re.search(r"(?<![a-z0-9])[lc]\s?\d", tl):
        fam = spec["material_family"] = "carbon steel"
        notes.append("Structural shape with no material named: read as carbon steel A36 (trade convention for L/C shapes)")
    if fam == "carbon steel" and shape == "angle" and spec["grade"] is None:
        spec["grade"] = "A36"

    spec.update(shape=shape, thickness_in=thickness, gauge=gauge, width_in=width, height_in=height,
                length_in=length, od_in=od)
    m = re.search(r"\bastm\s*([ab]\d{2,4})", tl)
    if m:
        spec["standard"] = "ASTM " + m[1].upper()

    if uom and uom.lower() in ("ft", "feet", "lf"):
        uom = "ft"
    elif uom:
        uom = "EA"

    return {
        "raw": raw.strip(),
        "qty": qty,
        "uom": uom,
        "qty_raw": None if qty_hint in (None, "") else str(qty_hint),
        "spec": spec,
        "notes": notes,
        "assumptions": assumptions,
    }


def ft_to_lengths(qty_ft: float, length_in: float) -> int:
    return math.ceil(qty_ft * 12 / length_in)
