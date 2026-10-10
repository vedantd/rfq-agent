"""Reference data from the RudCo demo dataset: gauge tables, synonyms, benchmarks, compliance rules, market index."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
# The shared dataset lives at the repo root; override with RUDCO_DATA_DIR.
DATA_DIR = Path(os.environ.get("RUDCO_DATA_DIR", BACKEND_DIR.parent / "rudco_demo_data"))
DEMO_DB = DATA_DIR / "rudco_demo.db"
# Runtime state (RFQs, edited catalog, traces). Git-ignored; delete to reset.
RUNTIME_DIR = BACKEND_DIR / "var"
RUNTIME_DIR.mkdir(exist_ok=True)


def _rows(table: str) -> list[dict]:
    con = sqlite3.connect(DEMO_DB)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(f"select * from {table}")]
    finally:
        con.close()


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class RefData:
    sheet_gauge: dict[str, dict[int, float]] = field(default_factory=dict)  # family -> gauge -> inches
    tube_wall_gauge: dict[int, float] = field(default_factory=dict)
    benchmarks: dict[str, dict] = field(default_factory=dict)
    compliance_rules: list[dict] = field(default_factory=list)
    market_index: dict[str, dict] = field(default_factory=dict)  # index_id -> latest row
    synonyms: list[dict] = field(default_factory=list)
    answer_key: list[dict] = field(default_factory=list)


@lru_cache(maxsize=1)
def ref() -> RefData:
    r = RefData()
    cols = {
        "stainless steel": "stainless_in",
        "galvanized steel": "galvanized_in",
        "carbon steel": "carbon_steel_msg_in",
        "aluminum": "aluminum_bs_in",
    }
    for fam in cols:
        r.sheet_gauge[fam] = {}
    for row in _rows("gauge_table"):
        g = int(row["gauge"])
        for fam, col in cols.items():
            r.sheet_gauge[fam][g] = float(row[col])
    for row in _rows("tube_wall_gauge"):
        r.tube_wall_gauge[int(row["gauge"])] = float(row["wall_in"])
    for row in _rows("price_benchmarks"):
        for k in ("low_per_lb", "median_per_lb", "high_per_lb"):
            row[k] = _num(row[k])
        r.benchmarks[row["benchmark_id"]] = row
    r.compliance_rules = _rows("compliance_rules")
    for row in _rows("market_index"):
        cur = r.market_index.get(row["index_id"])
        if cur is None or row["month"] > cur["month"]:
            row["value"] = _num(row["value"])
            r.market_index[row["index_id"]] = row
    r.synonyms = _rows("synonyms")
    r.answer_key = _rows("answer_key")
    return r


def demo_catalog_rows() -> list[dict]:
    return _rows("catalog")
