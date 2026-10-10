"""FRED market context: synthetic fallback without a key, and context attached to priced lines.
No network: FRED_API_KEY is removed and live fetches are stubbed."""
import pytest

from ai import engine, market


@pytest.fixture(autouse=True)
def no_fred(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    market.clear_cache()
    yield
    market.clear_cache()


def test_synthetic_without_key():
    d = market.fetch_indices()
    assert d["mode"] == "synthetic" and d["fred_configured"] is False
    assert d["indices"] and all(i["live"] is False for i in d["indices"])


def test_live_mode_uses_fred_values(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    monkeypatch.setattr(market, "_fetch_live", lambda key: [{
        "series_id": "PNICKUSDM", "name": "Global price of Nickel (IMF)", "unit": "USD per metric ton",
        "commodity": "nickel", "value": 16632.36, "as_of": "2026-07-01", "live": True,
        "source": "FRED", "source_url": "https://fred.stlouisfed.org/series/PNICKUSDM"}])
    d = market.fetch_indices()
    assert d["mode"] == "fred_live"
    ctx = market.market_context_for_line("stainless_steel", "304")
    assert ctx["live"] and ctx["series_id"] == "PNICKUSDM" and "16,632.36" in ctx["citation"]


def test_priced_line_carries_market_context():
    line = {"id": "line_001", "raw_text": "304 SS sheet 16ga 4x8, qty 24", "material": "stainless_steel", "form": "sheet",
            "grade": "304", "thickness_in": 0.0625, "width_in": 48, "length_in": 96, "quantity": 24}
    out = engine.analyze_line(line)
    assert out["pricing"], out.get("blockers")
    ctx = out["pricing"]["market_context"]
    assert ctx and ctx["live"] is False and ctx["citation"]


def test_no_false_percentage_for_per_lb_benchmarks_without_weight():
    # A $/lb benchmark must never be compared with a per-sheet price.
    line = {"id": "line_001", "raw_text": "304 SS sheet 16ga 4x8, qty 24", "material": "stainless_steel", "form": "sheet",
            "grade": "304", "thickness_in": 0.0625, "width_in": 48, "length_in": 96, "quantity": 24}
    p = engine.analyze_line(line)["pricing"]
    if p["benchmark_basis"] == "per_lb":
        assert p["unit_price_per_lb"] and p["benchmark_per_lb"]
    else:
        assert p["benchmark_per_lb"] is None
