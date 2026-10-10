"""Product photo for an RFQ line (rudco_demo_data/catalog/images, one render per product type)."""
from __future__ import annotations

import re

_IMG = {
    ("stainless", "plate"): "ss_plate", ("stainless", "round_tube"): "ss_round_tube",
    ("stainless", "square_tube"): "ss_square_tube", ("stainless", "flat_bar"): "ss_flat_bar",
    ("aluminum", "plate"): "al_plate", ("aluminum", "angle"): "al_angle", ("aluminum", "channel"): "al_channel",
    ("aluminum", "square_tube"): "al_box_tube", ("aluminum", "round_tube"): "al_box_tube",
    ("aluminum", "tread_plate"): "al_tread_plate",
    ("carbon", "plate"): "cs_plate", ("carbon", "sheet"): "cs_plate", ("carbon", "angle"): "cs_angle",
    ("carbon", "flat_bar"): "cs_flat_bar", ("carbon", "square_tube"): "cs_hss", ("carbon", "round_tube"): "cs_hss",
    ("galvanized", "sheet"): "galv_sheet", ("galvanized", "plate"): "galv_sheet",
}


def product_image(line: dict) -> str | None:
    """URL of the photo for this line, from material/form/finish; the request text fills empty fields."""
    t = f" {line.get('raw_text') or ''} ".lower()
    m = (line.get("material") or "").lower()
    f = (line.get("form") or "").lower()
    if "galv" in m or re.search(r"\bgalv|\bg90\b|\bg60\b", t):
        mat = "galvanized"
    elif "stainless" in m or re.search(r"stainless|\bss\b|\bs/s\b|ss3\d\d|\b30[0-9]l?\b|\b316l?\b", t):
        mat = "stainless"
    elif "alum" in m or re.search(r"\balum|\b(3003|5052|5005|6061|6063)\b", t):
        mat = "aluminum"
    elif "carbon" in m or re.search(r"\ba36\b|\bhr\b|\bhss\b|\bcarbon\b|\bmild steel\b|\ba500\b|(?<![a-z0-9])l\s?\d", t):
        mat = "carbon"
    else:
        return None
    if re.search(r"diamond|tread|checker", t):
        shape = "tread_plate"
    elif re.search(r"\bhss\b|square tube|sq tube|rect\w*\.? tub|box tube", t):
        shape = "square_tube"
    elif re.search(r"\btub(e|es|ing)\b|\bod\b|\bpipe\b", t):
        shape = "round_tube"
    elif re.search(r"flat\s*bar|\bfb\b", t):
        shape = "flat_bar"
    elif re.search(r"\bangle\b|(?<![a-z0-9])l\s?\d", t):
        shape = "angle"
    elif re.search(r"\bchannel\b", t):
        shape = "channel"
    elif "plate" in f or re.search(r"\bplate\b|\bplt\b|\bpl\b", t):
        shape = "plate"
    else:
        shape = "sheet"
    key = _IMG.get((mat, shape))
    if key is None and shape == "sheet":
        if mat == "stainless":
            key = ("ss_sheet_4" if re.search(r"#\s?4|no\.?\s?4|brushed|satin|polished", t)
                   else "ss_sheet_ba" if re.search(r"\bba\b|bright anneal|mirror|#\s?8", t) else "ss_sheet_2b")
        elif mat == "aluminum":
            key = "al_sheet_anodized" if "anod" in t else "al_sheet_mill"
    return f"/v1/catalog/images/{key}.jpg" if key else None
