"""Live commodity context for the price step, from the St. Louis Fed FRED API.

Labeled context only: it never overwrites catalog unit prices (those stay synthetic and quotes stay
demo_draft). Without FRED_API_KEY, or when FRED is unreachable, it falls back to the synthetic
market_index table in rudco_demo_data and says so (live: false).
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

import httpx

import database

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
CACHE_SECONDS = 3600
SERIES: dict[str, dict[str, str]] = {
    "PNICKUSDM": {"name": "Global price of Nickel (IMF)", "unit": "USD per metric ton", "commodity": "nickel"},
    "PALUMUSDM": {"name": "Global price of Aluminum (IMF)", "unit": "USD per metric ton", "commodity": "aluminum"},
    "WPU102504": {"name": "PPI: Nickel and nickel-base alloy mill shapes (BLS)", "unit": "index 1982=100", "commodity": "nickel_mill"},
    "WPU102501": {"name": "PPI: Aluminum mill shapes (BLS)", "unit": "index 1982=100", "commodity": "aluminum_mill"},
}
# Which headline series gives context for which material (stainless is ~8-10% nickel and priced off it)
MATERIAL_SERIES = {"stainless": "PNICKUSDM", "aluminum": "PALUMUSDM"}

_cache: dict[str, Any] = {"at": 0.0, "data": None}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache["at"], _cache["data"] = 0.0, None


def _key() -> str:
    return os.getenv("FRED_API_KEY", "").strip()


def _fetch_live(key: str) -> list[dict]:
    out = []
    with httpx.Client(timeout=10) as client:
        for sid, meta in SERIES.items():
            r = client.get(FRED_URL, params={"series_id": sid, "api_key": key, "file_type": "json",
                                             "sort_order": "desc", "limit": 6})
            r.raise_for_status()
            obs = [o for o in r.json().get("observations", []) if o.get("value") not in (".", None, "")]
            if not obs:
                continue
            out.append({"series_id": sid, **meta, "value": round(float(obs[0]["value"]), 2), "as_of": obs[0]["date"],
                        "live": True, "source": "FRED (Federal Reserve Bank of St. Louis)",
                        "source_url": f"https://fred.stlouisfed.org/series/{sid}"})
    return out


def _synthetic() -> list[dict]:
    """Latest month per index from the demo dataset's market_index table (labelled synthetic)."""
    latest: dict[str, dict] = {}
    for row in database.load_market_index():
        cur = latest.get(row["index_id"])
        if cur is None or str(row["month"]) > str(cur["month"]):
            latest[row["index_id"]] = row
    out = []
    for row in latest.values():
        name = str(row.get("name") or row["index_id"])
        low = name.lower()
        commodity = "nickel" if "nickel" in low else "aluminum" if "alumin" in low else row["index_id"].lower()
        try:
            value = round(float(row["value"]), 2)
        except (TypeError, ValueError):
            value = None
        out.append({"series_id": row["index_id"], "name": name, "unit": row.get("unit"), "commodity": commodity,
                    "value": value, "as_of": row.get("month"), "live": False,
                    "source": row.get("source") or "SYNTHETIC demo data", "source_url": None})
    return out


def fetch_indices() -> dict:
    """{mode, fred_configured, indices[], note}. Cached for an hour; never raises."""
    with _lock:
        if _cache["data"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["data"]
    key = _key()
    data: dict
    if key:
        try:
            indices = _fetch_live(key)
            if indices:
                data = {"mode": "fred_live", "fred_configured": True, "indices": indices,
                        "note": "Live FRED observations, used as market context only; catalog prices stay synthetic."}
            else:
                raise ValueError("FRED returned no observations")
        except (httpx.HTTPError, ValueError) as exc:
            data = {"mode": "synthetic_fallback", "fred_configured": True, "indices": _synthetic(),
                    "note": f"FRED unavailable ({type(exc).__name__}); showing synthetic demo index."}
    else:
        data = {"mode": "synthetic", "fred_configured": False, "indices": _synthetic(),
                "note": "Set FRED_API_KEY for live FRED data; showing synthetic demo index."}
    with _lock:
        _cache["at"], _cache["data"] = time.time(), data
    return data


def market_context_for_line(material: str | None, grade: str | None = None) -> dict | None:
    """Citation for the commodity that drives this material's price, or None if none applies."""
    m = (material or "").lower()
    kind = "stainless" if "stainless" in m or str(grade or "").startswith(("304", "316")) else "aluminum" if "alum" in m else None
    if not kind:
        return None
    data = fetch_indices()
    want = MATERIAL_SERIES[kind]
    commodity = "nickel" if kind == "stainless" else "aluminum"
    pick = next((i for i in data["indices"] if i["series_id"] == want), None) or \
        next((i for i in data["indices"] if i.get("commodity") == commodity), None)
    if not pick or pick.get("value") is None:
        return None
    label = f"FRED {pick['series_id']}" if pick["live"] else f"synthetic {pick['series_id']}"
    return {
        "series_id": pick["series_id"], "name": pick["name"], "value": pick["value"], "unit": pick.get("unit"),
        "as_of": pick.get("as_of"), "live": pick["live"], "source": pick.get("source"), "source_url": pick.get("source_url"),
        "driver": f"{commodity} drives {kind} prices",
        "citation": f"{pick['name']} {pick['value']:,.2f} {pick.get('unit') or ''} as of {pick.get('as_of')} ({label})".replace("  ", " "),
    }
