"""Score the pipeline against the dataset's answer key (32 lines across 4 RFQs)."""
from __future__ import annotations

from .ingest import ingest_file
from .pipeline import process
from .refdata import DATA_DIR, ref

SAMPLES = {
    "RFQ-01": "rfq_01_hotel_lobby_email.eml",
    "RFQ-02": "rfq_02_transit_buy_america_email.eml",
    "RFQ-03": "rfq_03_residential_gc_form.pdf",
    "RFQ-04": "rfq_04_fabricator_bom.xlsx",
}


def compliance_class(text: str) -> str:
    t = (text or "").strip().upper()
    for c in ("BLOCK", "WARN", "OK"):
        if t.startswith(c):
            return c
    return "n/a" if t.startswith("N/A") else ("OK" if t.startswith("SAME") else t[:5])


def run_eval() -> dict:
    key = ref().answer_key
    rows = []
    for rfq_code, fname in SAMPLES.items():
        data = (DATA_DIR / "rfqs" / fname).read_bytes()
        rfq = process(ingest_file(data, fname), run_name=f"eval:{rfq_code}")
        by_no = {l["line_no"]: l for l in rfq["lines"]}
        for k in (k for k in key if k["rfq_id"] == rfq_code):
            l = by_no.get(int(k["line_no"]))
            exp_skus = [s for s in (k["expected_skus"] or "").split(";") if s]
            got_status = l["status"] if l else "MISSING"
            sku_ok = None
            if k["expected_status"] in ("MATCH", "MATCH_ASSUMPTION") and l:
                sku_ok = l.get("selected_sku") in exp_skus
            exp_c = compliance_class(k["compliance_result"])
            got_c = l["compliance"]["result"] if l else "MISSING"
            comp_ok = None if exp_c in ("n/a", "") or k["expected_status"] in ("CLARIFY", "NO_MATCH") else got_c == exp_c
            rows.append({
                "rfq": rfq_code, "line": int(k["line_no"]), "raw": k["raw_text"],
                "expected_status": k["expected_status"], "status": got_status, "status_ok": got_status == k["expected_status"],
                "asks_question_ok": (bool(l and l.get("question")) if k["expected_status"] in ("CLARIFY", "NO_MATCH") else None),
                "expected_skus": exp_skus, "selected_sku": l.get("selected_sku") if l else None, "sku_ok": sku_ok,
                "expected_compliance": exp_c, "compliance": got_c, "compliance_ok": comp_ok,
                "question": l.get("question") if l else None, "assumptions": l.get("assumptions") if l else None,
            })
    def rate(field):
        vals = [r[field] for r in rows if r[field] is not None]
        return {"correct": sum(vals), "total": len(vals), "rate": round(sum(vals) / len(vals), 3) if vals else None}
    # "never guess": every line the key says must go back to the buyer must not be priced
    must_ask = [r for r in rows if r["expected_status"] in ("CLARIFY", "NO_MATCH")]
    guessed = [r for r in must_ask if r["status"] in ("MATCH", "MATCH_ASSUMPTION")]
    return {
        "status": rate("status_ok"), "sku": rate("sku_ok"), "compliance": rate("compliance_ok"),
        "asks_when_it_should": rate("asks_question_ok"),
        "guessed_instead_of_asking": len(guessed),
        "rows": rows,
    }
