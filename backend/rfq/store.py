"""SQLite store for RFQs and the (editable) supplier catalog. The demo dataset DB is never modified."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .refdata import RUNTIME_DIR, demo_catalog_rows

APP_DB = RUNTIME_DIR / "app.db"
NUMERIC = {"thickness_in", "width_in", "height_in", "length_in", "weight_lb_each", "price_per_lb", "unit_price",
           "unit_price_qty10", "unit_price_qty50", "recycled_content_pct", "stock_qty", "lead_time_days", "min_order_qty"}
_lock = threading.RLock()


def _con(path: Path = APP_DB) -> sqlite3.Connection:
    con = sqlite3.connect(path, check_same_thread=False)
    con.execute("create table if not exists rfqs (id text primary key, created_at text, doc text)")
    con.execute("create table if not exists catalog (sku text primary key, doc text)")
    return con


def _clean_item(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if k in NUMERIC:
            try:
                out[k] = None if v in (None, "") else float(v)
            except (TypeError, ValueError):
                out[k] = None
        else:
            out[k] = "" if v is None else v
    return out


def init():
    with _lock, _con() as con:
        if con.execute("select count(*) from catalog").fetchone()[0] == 0:
            for row in demo_catalog_rows():
                item = _clean_item(row)
                con.execute("insert into catalog values (?, ?)", (item["sku"], json.dumps(item)))


def reset():
    """Drop all RFQs and restore the demo catalog (used by tests and POST /v1/admin/reset)."""
    with _lock, _con() as con:
        con.execute("delete from rfqs")
        con.execute("delete from catalog")
    init()


# ---------- rfqs ----------
def save_rfq(doc: dict):
    with _lock, _con() as con:
        con.execute("insert or replace into rfqs values (?, ?, ?)", (doc["id"], doc["created_at"], json.dumps(doc)))


def get_rfq(rfq_id: str) -> dict | None:
    with _lock, _con() as con:
        row = con.execute("select doc from rfqs where id = ?", (rfq_id,)).fetchone()
    return json.loads(row[0]) if row else None


def list_rfqs() -> list[dict]:
    with _lock, _con() as con:
        rows = con.execute("select doc from rfqs order by created_at desc").fetchall()
    return [json.loads(r[0]) for r in rows]


# ---------- catalog ----------
def catalog_all() -> list[dict]:
    with _lock, _con() as con:
        return [json.loads(r[0]) for r in con.execute("select doc from catalog order by sku")]


def catalog_get(sku: str) -> dict | None:
    with _lock, _con() as con:
        row = con.execute("select doc from catalog where sku = ?", (sku,)).fetchone()
    return json.loads(row[0]) if row else None


def catalog_put(sku: str, fields: dict) -> tuple[dict, bool]:
    """Create or update a catalog item. Returns (item, created)."""
    with _lock:
        cur = catalog_get(sku)
        created = cur is None
        item = dict(cur or {"sku": sku})
        item.update(_clean_item({k: v for k, v in fields.items() if k != "sku"}))
        item["sku"] = sku
        # keep unit prices consistent when only $/lb or weight changed
        if ("price_per_lb" in fields or "weight_lb_each" in fields) and "unit_price" not in fields:
            ppl, w = item.get("price_per_lb"), item.get("weight_lb_each")
            if ppl and w:
                item["unit_price"] = round(ppl * w, 2)
                item["unit_price_qty10"] = round(item["unit_price"] * 0.95, 2)
                item["unit_price_qty50"] = round(item["unit_price"] * 0.91, 2)
        with _con() as con:
            con.execute("insert or replace into catalog values (?, ?)", (sku, json.dumps(item)))
        return item, created
