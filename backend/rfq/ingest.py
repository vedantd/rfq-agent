"""Turn an uploaded RFQ (email, text, PDF, spreadsheet, image) into candidate lines + header text."""
from __future__ import annotations

import csv
import email
import io
import re
from dataclasses import dataclass, field
from email import policy

from .providers import Attachment

IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
MATERIAL_HINT = re.compile(r"\b(ss|stainless|alum|aluminum|galv|steel|plate|sheet|sht|tube|bar|angle|hss|a36|brass|duplex|(304|316)l?|5052|6061|6063|3003|5005)\b", re.I)
DIM_HINT = re.compile(r"\d\s*(ga|gauge)\b|\d\s*['\"]?\s*x\s*\d", re.I)


@dataclass
class Row:
    line_no: int
    raw: str
    qty_hint: object = None
    uom_hint: str | None = None
    notes: str | None = None


@dataclass
class Ingested:
    source_type: str                     # email | text | pdf | xlsx | csv | image
    filename: str | None = None
    full_text: str = ""
    header_text: str = ""
    rows: list[Row] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    attachments: list[Attachment] = field(default_factory=list)  # for the LLM (images, scanned PDFs)
    needs_llm: bool = False              # nothing readable without a vision model
    warnings: list[str] = field(default_factory=list)


# ---------- free text ----------
BULLET = re.compile(r"^\s*(?:[-*•]\s+|\d{1,3}[.)]\s+)(.+)$")
PAREN_QTY = re.compile(r"^\s*\(\d+\)\s*\S")


def split_text(text: str) -> tuple[list[Row], str]:
    rows, header = [], []
    for ln in text.splitlines():
        m = BULLET.match(ln)
        if m and MATERIAL_HINT.search(m[1]):
            rows.append(Row(len(rows) + 1, m[1].strip()))
        elif PAREN_QTY.match(ln) and (MATERIAL_HINT.search(ln) or DIM_HINT.search(ln)):
            rows.append(Row(len(rows) + 1, ln.strip()))
        else:
            header.append(ln)
    if not rows:  # no bullets: any line that looks like a material line
        header = []
        for ln in text.splitlines():
            if MATERIAL_HINT.search(ln) and re.search(r"\d", ln) and len(ln) < 200:
                rows.append(Row(len(rows) + 1, ln.strip()))
            else:
                header.append(ln)
    return rows, "\n".join(header).strip()


def from_text(text: str, source_type="text", filename=None, meta=None) -> Ingested:
    rows, header = split_text(text)
    return Ingested(source_type, filename, text, header, rows, meta or {})


def from_email(data: bytes, filename=None) -> Ingested:
    msg = email.message_from_bytes(data, policy=policy.default)
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    meta = {"subject": str(msg.get("subject", "")), "from": str(msg.get("from", "")), "date": str(msg.get("date", ""))}
    ing = from_text(text, "email", filename, meta)
    ing.header_text = f"Subject: {meta['subject']}\nFrom: {meta['from']}\n{ing.header_text}"
    return ing


# ---------- tables (xlsx / csv / pdf tables) ----------
def _norm(c) -> str:
    return re.sub(r"\s+", " ", str(c or "")).strip().lower()


def _find_header(table: list[list]) -> tuple[int, dict] | None:
    for i, row in enumerate(table):
        cols = {}
        for j, c in enumerate(row):
            n = _norm(c)
            if n in ("desc", "description", "item description", "material", "material description") and "desc" not in cols:
                cols["desc"] = j
            elif n in ("qty", "quantity", "qty.") and "qty" not in cols:
                cols["qty"] = j
            elif n in ("units", "unit", "u/m", "uom", "um") and "uom" not in cols:
                cols["uom"] = j
            elif n in ("item", "line", "#", "line no", "item no") and "line" not in cols:
                cols["line"] = j
            elif n in ("notes", "note", "remarks", "comments") and "notes" not in cols:
                cols["notes"] = j
        if "desc" in cols and "qty" in cols:
            return i, cols
    return None


def from_table(table: list[list], source_type, filename=None, extra_header="") -> Ingested | None:
    found = _find_header(table)
    if not found:
        return None
    hi, cols = found
    header_lines = [" ".join(str(c) for c in r if c not in (None, "")) for r in table[:hi]]
    rows, trailing = [], []
    for r in table[hi + 1:]:
        cell = lambda k: r[cols[k]] if k in cols and cols[k] < len(r) else None
        desc = cell("desc")
        if desc in (None, ""):
            txt = " ".join(str(c) for c in r if c not in (None, ""))
            if txt:
                trailing.append(txt)
            continue
        line_no = cell("line")
        try:
            line_no = int(float(line_no))
        except (TypeError, ValueError):
            line_no = len(rows) + 1
        rows.append(Row(line_no, re.sub(r"\s+", " ", str(desc)).strip(), cell("qty"),
                        None if cell("uom") in (None, "") else str(cell("uom")), None if cell("notes") in (None, "") else str(cell("notes"))))
    header = "\n".join([extra_header, *header_lines, *trailing]).strip()
    full = "\n".join(" | ".join("" if c is None else str(c) for c in r) for r in table)
    return Ingested(source_type, filename, full, header, rows, {"table": True})


def from_xlsx(data: bytes, filename=None) -> Ingested:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    sheets, skipped = [], []
    for ws in wb.worksheets:
        table = [list(r) for r in ws.iter_rows(values_only=True)]
        first = next((str(c) for r in table for c in r if c not in (None, "")), "")
        if ws.sheet_state != "visible" or re.search(r"old|superseded", ws.title, re.I) or re.search(r"superseded", first, re.I):
            skipped.append(ws.title)
        else:
            sheets.append((ws, table))
    for ws, table in sheets:
        ing = from_table(table, "xlsx", filename)
        if ing:
            if skipped:
                ing.warnings.append(f"Ignored superseded sheet(s): {', '.join(skipped)}")
            ing.meta["sheet"] = ws.title
            return ing
    return Ingested("xlsx", filename, warnings=["No sheet with a Description and Qty column was found"])


def from_csv(data: bytes, filename=None) -> Ingested:
    text = data.decode("utf-8-sig", errors="replace")
    table = list(csv.reader(io.StringIO(text)))
    return from_table(table, "csv", filename) or from_text(text, "csv", filename)


def from_pdf(data: bytes, filename=None) -> Ingested:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        best = None
        for p in pdf.pages:
            for t in p.extract_tables():
                ing = from_table(t, "pdf", filename)
                if ing and ing.rows:
                    best = ing
                    break
            if best:
                break
        if best:
            best.full_text = text
            # requirement text lives outside the table on forms
            best.header_text = text
            return best
        if text.strip():
            return from_text(text, "pdf", filename)
        # scanned PDF: render pages for a vision model
        imgs = []
        for p in pdf.pages[:10]:
            buf = io.BytesIO()
            p.to_image(resolution=150).original.save(buf, format="PNG")
            imgs.append(Attachment(buf.getvalue(), "image/png", f"page{p.page_number}.png"))
    ing = Ingested("pdf", filename, needs_llm=True)
    ing.attachments = [Attachment(data, "application/pdf", filename or "rfq.pdf"), *imgs]
    return ing


def from_image(data: bytes, media_type: str, filename=None) -> Ingested:
    return Ingested("image", filename, needs_llm=True, attachments=[Attachment(data, media_type, filename or "rfq")])


def ingest_file(data: bytes, filename: str) -> Ingested:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext == "eml":
        return from_email(data, filename)
    if ext in ("xlsx", "xlsm"):
        return from_xlsx(data, filename)
    if ext == "csv":
        return from_csv(data, filename)
    if ext == "pdf":
        return from_pdf(data, filename)
    if ext in IMAGE_TYPES:
        return from_image(data, IMAGE_TYPES[ext], filename)
    if ext in ("txt", "md", ""):
        return from_text(data.decode("utf-8", errors="replace"), "text", filename)
    raise ValueError(f"Unsupported file type '.{ext}'. Send PDF, CSV, XLSX, EML, TXT, PNG or JPG.")
