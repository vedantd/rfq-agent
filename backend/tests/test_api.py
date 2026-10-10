"""End-to-end API tests on the dataset's sample RFQs. Run: uv run pytest -q"""
import os

os.environ["LLM_PROVIDER"] = "rules"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from rfq import store  # noqa: E402
from rfq.refdata import DATA_DIR  # noqa: E402


@pytest.fixture(scope="module")
def client():
    store.reset()
    with TestClient(app) as c:
        yield c
    store.reset()


def upload(client, name):
    path = DATA_DIR / "rfqs" / name
    r = client.post("/v1/rfqs/upload", files={"file": (name, path.read_bytes())})
    assert r.status_code == 201, r.text
    return r.json()


def line(rfq, n):
    return next(l for l in rfq["lines"] if l["line_no"] == n)


def test_health(client):
    r = client.get("/v1/health").json()
    assert r["ok"] and r["catalog_items"] == 99 and r["llm"]["active"] == "rules"


def test_email_rfq_parses_and_asks(client):
    rfq = upload(client, "rfq_01_hotel_lobby_email.eml")
    assert rfq["summary"]["lines"] == 8
    assert line(rfq, 3)["spec"]["thickness_in"] == 0.065           # 16 ga *tube* wall, not sheet 0.060
    assert line(rfq, 6)["spec"]["thickness_in"] == 0.0516          # galvanized gauge table
    assert line(rfq, 8)["status"] == "CLARIFY"                     # "use your best judgment" still asks
    assert line(rfq, 2)["status"] == "CLARIFY" and "finish" in line(rfq, 2)["clarify_fields"]
    q = client.get(f"/v1/rfqs/{rfq['id']}/clarifications").json()
    assert q["count"] == 2 and q["email"]["body"]


def test_clarify_then_approve_then_quote(client):
    rfq = upload(client, "rfq_01_hotel_lobby_email.eml")
    rid = rfq["id"]
    r = client.patch(f"/v1/rfqs/{rid}/lines/L2", json={"answer": "2B"})
    assert r.status_code == 200, r.text
    l2 = r.json()["line"]
    assert l2["status"] == "MATCH" and l2["selected_sku"].startswith("SS304-2B-16G-4896")
    assert client.post(f"/v1/rfqs/{rid}/lines/L8/approve").status_code == 409   # still unclear
    a = client.post(f"/v1/rfqs/{rid}/lines/L2/approve", json={})
    assert a.status_code == 200 and a.json()["approved"]
    quote = client.post(f"/v1/rfqs/{rid}/quotes/draft", json={}).json()
    assert {i["line_no"] for i in quote["lines"]} == {1, 2, 3, 4, 5, 6, 7}
    assert quote["subtotal"] > 0 and quote["excluded_lines"][0]["line_no"] == 8
    only = client.post(f"/v1/rfqs/{rid}/quotes/draft", json={"approved_only": True}).json()
    assert [i["line_no"] for i in only["lines"]] == [2]


def test_buy_america_blocks_and_picks_domestic(client):
    rfq = upload(client, "rfq_02_transit_buy_america_email.eml")
    assert line(rfq, 6)["selected_sku"] == "SS304-2B-16G-4896-US"   # TW is cheaper but fails Buy America
    assert line(rfq, 7)["compliance"]["result"] == "BLOCK"          # origin US, melted in MX
    assert line(rfq, 5)["status"] == "NO_MATCH"                     # duplex not stocked, never substituted
    rid = rfq["id"]
    assert client.post(f"/v1/rfqs/{rid}/lines/L7/approve").status_code == 409
    assert client.post(f"/v1/rfqs/{rid}/lines/L7/approve", json={"override_block": True}).status_code == 200
    l4 = client.patch(f"/v1/rfqs/{rid}/lines/L4", json={"answer": "20 ft"}).json()["line"]
    assert l4["status"] == "MATCH" and l4["selected_sku"] == "HSS500-SQ-2x2x188-240-US"


def test_pdf_and_xlsx(client):
    pdf = upload(client, "rfq_03_residential_gc_form.pdf")
    assert pdf["summary"]["lines"] == 8 and line(pdf, 1)["qty"] == 6
    assert "aama611" in pdf["requirements"] and "no_substitution" in pdf["requirements"]
    xl = upload(client, "rfq_04_fabricator_bom.xlsx")
    assert xl["summary"]["lines"] == 8 and any("superseded" in w.lower() for w in xl["warnings"])
    assert line(xl, 6)["qty_ea"] == 15                              # 300 ft -> 15 x 20 ft
    assert line(xl, 2)["duplicate_of"] == "L1"
    assert line(xl, 8)["price"]["position"] == "above_range"        # honest about being above market


def test_text_rfq(client):
    r = client.post("/v1/rfqs", json={"text": "Need pricing:\n- 304 SS sheet 16ga 4x8 #4 qty 5\n- galv 20ga 4x8 G90 x 10"})
    assert r.status_code == 201
    rfq = r.json()
    assert rfq["summary"]["lines"] == 2 and line(rfq, 1)["status"] == "MATCH"


def test_image_without_llm_is_a_clear_error(client):
    r = client.post("/v1/rfqs/upload", files={"file": ("photo.png", b"\x89PNG fake")})
    assert r.status_code == 422 and "LLM" in r.json()["detail"]


def test_unknown_ids_and_types(client):
    assert client.get("/v1/rfqs/rfq_nope").status_code == 404
    assert client.post("/v1/rfqs/upload", files={"file": ("x.docx", b"abc")}).status_code == 415


def test_catalog_put(client):
    r = client.put("/v1/catalog/items/SS304-2B-16G-4896-US", json={"price_per_lb": 3.10})
    assert r.status_code == 200 and r.json()["unit_price"] == round(3.10 * r.json()["weight_lb_each"], 2)
    r = client.put("/v1/catalog/items/NEW-SKU-1", json={"description": "test", "material_family": "brass"})
    assert r.status_code == 201


def test_answer_key_eval(client):
    from rfq.evaluation import run_eval
    res = run_eval()
    assert res["guessed_instead_of_asking"] == 0
    assert res["status"]["rate"] >= 0.9 and res["sku"]["rate"] >= 0.9 and res["compliance"]["rate"] >= 0.85
