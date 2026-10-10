"""RudCo RFQ-to-Quote API.  Run: uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
Interactive docs at /docs."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from pydantic import BaseModel, Field

from rfq import pipeline, store, tracing
from rfq.evaluation import SAMPLES, run_eval
from rfq.ingest import from_text, ingest_file
from rfq.pipeline import PipelineError
from rfq.providers import provider_status
from rfq.refdata import DATA_DIR

MAX_UPLOAD = 15 * 1024 * 1024
STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init()
    yield


app = FastAPI(title="RudCo RFQ to Quote", version="0.1.0", lifespan=lifespan,
              description="Messy RFQ in, ready-to-send quote out. Ambiguous lines go back to the buyer as questions.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/", include_in_schema=False)
def desk():
    """The RFQ Desk test UI."""
    return FileResponse(STATIC / "index.html")


@app.exception_handler(PipelineError)
def _pipeline_error(_: Request, e: PipelineError):
    return JSONResponse(status_code=e.status, content={"detail": str(e)})


# ---------- request bodies ----------
class RFQText(BaseModel):
    text: str = Field(..., description="The RFQ as pasted text (email body, list, etc.)")
    subject: str | None = None
    sender: str | None = Field(None, description="From line, e.g. 'Dana Whitfield <dana@example.com>'")


class LinePatch(BaseModel):
    answer: str | None = Field(None, description="The buyer's answer in plain words, e.g. '2B' or '20 ft' or 'G90, 4x10'")
    qty: float | None = None
    spec: dict[str, Any] | None = Field(None, description="Explicit spec overrides, e.g. {'finish': '2B'}")
    selected_sku: str | None = Field(None, description="Pick a different eligible SKU")
    remove: bool | None = Field(None, description="Drop the line from the quote")


class Approve(BaseModel):
    sku: str | None = None
    override_block: bool = False
    note: str | None = None


class DraftQuote(BaseModel):
    approved_only: bool = Field(False, description="Only include lines a person approved")


def _brief(rfq: dict) -> dict:
    return {k: rfq.get(k) for k in ("id", "created_at", "updated_at", "reference", "buyer", "status", "summary", "source")}


# ---------- RFQs ----------
@app.post("/v1/rfqs", status_code=201, tags=["rfqs"], summary="Ingest a messy RFQ (pasted text)")
def create_rfq(body: RFQText):
    meta = {"subject": body.subject or "", "from": body.sender or ""}
    ing = from_text(body.text, "text", None, meta)
    if body.subject or body.sender:
        ing.header_text = f"Subject: {body.subject or ''}\nFrom: {body.sender or ''}\n{ing.header_text}"
    return pipeline.process(ing)


@app.post("/v1/rfqs/upload", status_code=201, tags=["rfqs"], summary="Upload an RFQ file (PDF, CSV, XLSX, EML, TXT, PNG, JPG)")
async def upload_rfq(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 15 MB")
    try:
        ing = ingest_file(data, file.filename or "upload")
    except ValueError as e:
        raise HTTPException(415, str(e))
    return pipeline.process(ing)


@app.get("/v1/rfqs", tags=["rfqs"], summary="List RFQs (summaries)")
def list_rfqs():
    return [_brief(r) for r in store.list_rfqs()]


@app.get("/v1/rfqs/{rfq_id}", tags=["rfqs"], summary="Structured specs, matches, pricing and compliance for every line")
def get_rfq(rfq_id: str):
    return pipeline.get(rfq_id)


@app.get("/v1/rfqs/{rfq_id}/clarifications", tags=["rfqs"], summary="Unresolved questions for the buyer")
def clarifications(rfq_id: str):
    rfq = pipeline.get(rfq_id)
    open_lines = [
        {"line_id": l["line_id"], "line_no": l["line_no"], "raw": l["raw"], "status": l["status"],
         "question": l["question"], "options": l.get("options") or [], "fields": l.get("clarify_fields") or [],
         "kind": ("duplicate" if l.get("duplicate_of") else "compliance" if l["compliance"]["result"] == "BLOCK"
                  else "not_stocked" if l["status"] == "NO_MATCH" else "missing_info")}
        for l in rfq["lines"] if l.get("question") and l["status"] != "REMOVED" and not l.get("approved")
    ]
    return {"rfq_id": rfq_id, "count": len(open_lines), "questions": open_lines, "email": rfq.get("clarification_email")}


@app.patch("/v1/rfqs/{rfq_id}/lines/{line_id}", tags=["lines"], summary="Apply a buyer clarification and re-evaluate the line")
def patch_line(rfq_id: str, line_id: str, body: LinePatch):
    rfq = pipeline.apply_clarification(rfq_id, line_id, body.model_dump(exclude_none=True))
    line = next(l for l in rfq["lines"] if l["line_id"] == line_id)
    return {"rfq": _brief(rfq), "line": line}


@app.post("/v1/rfqs/{rfq_id}/lines/{line_id}/approve", tags=["lines"], summary="Approve a validated line for the quote")
def approve_line(rfq_id: str, line_id: str, body: Approve = Body(default_factory=Approve)):
    return pipeline.approve(rfq_id, line_id, body.model_dump(exclude_none=True))


@app.post("/v1/rfqs/{rfq_id}/quotes/draft", status_code=201, tags=["quotes"], summary="Generate the quote JSON")
def draft_quote(rfq_id: str, body: DraftQuote = Body(default_factory=DraftQuote)):
    return pipeline.draft_quote(rfq_id, body.model_dump())


# ---------- catalog ----------
@app.get("/v1/catalog/items", tags=["catalog"], summary="List catalog items (optional text filter)")
def catalog_list(q: str | None = None):
    items = store.catalog_all()
    if q:
        ql = q.lower()
        items = [i for i in items if ql in i["sku"].lower() or ql in (i.get("description") or "").lower()]
    return items


@app.get("/v1/catalog/items/{sku}", tags=["catalog"])
def catalog_get(sku: str):
    item = store.catalog_get(sku)
    if not item:
        raise HTTPException(404, f"SKU {sku} not found")
    return item


@app.put("/v1/catalog/items/{sku}", tags=["catalog"], summary="Create or update a supplier catalog item")
def catalog_put(sku: str, fields: dict[str, Any] = Body(..., examples=[{"price_per_lb": 3.05, "stock_qty": 40}])):
    if not fields:
        raise HTTPException(400, "Send at least one field to update")
    item, created = store.catalog_put(sku, fields)
    return JSONResponse(status_code=201 if created else 200, content=item)


# ---------- demo helpers ----------
@app.get("/v1/samples", tags=["demo"], summary="The four sample RFQs from the dataset")
def samples():
    return [{"id": k, "filename": v} for k, v in SAMPLES.items()]


@app.post("/v1/samples/{sample_id}", status_code=201, tags=["demo"], summary="Run a sample RFQ through the pipeline")
def run_sample(sample_id: str):
    fname = SAMPLES.get(sample_id.upper())
    if not fname:
        raise HTTPException(404, f"Unknown sample. Use one of: {', '.join(SAMPLES)}")
    return pipeline.process(ingest_file((DATA_DIR / "rfqs" / fname).read_bytes(), fname), run_name=f"sample:{sample_id}")


@app.get("/v1/eval", tags=["demo"], summary="Score the pipeline against the dataset answer key")
def evaluation(details: bool = False):
    res = run_eval()
    if not details:
        res.pop("rows")
    return res


@app.get("/v1/traces", tags=["observability"], summary="Agent run traces (also sent to Block Convey PRISM when configured)")
def traces(rfq_id: str | None = None, limit: int = 100):
    return tracing.read_local(rfq_id, limit)


@app.get("/v1/health", tags=["observability"])
def health():
    return {"ok": True, "llm": provider_status(), "prism": tracing.prism_status(), "catalog_items": len(store.catalog_all())}
