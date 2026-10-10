# RudCo RFQ to Quote — backend

UI: open `http://localhost:8000/` (RFQ Desk: paste or upload an RFQ, answer questions, generate the quote).

Messy RFQ in (email, text, PDF, CSV, XLSX, image), ready-to-send quote out. Lines that are ambiguous go back to the buyer as questions, never guesses.

## Run

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Interactive API docs: `http://<host>:8000/docs`
- Tests (32-line answer key + API flows): `uv run pytest -q`
- Eval table: `uv run python scripts/eval.py` (add `--fails` to see only misses)

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/rfqs` | Ingest pasted text: `{"text": "...", "subject": "...", "sender": "Name <email>"}` |
| POST | `/v1/rfqs/upload` | Multipart `file`: PDF, CSV, XLSX, EML, TXT, PNG, JPG (images need an LLM) |
| GET | `/v1/rfqs` | List RFQs (summaries) |
| GET | `/v1/rfqs/{id}` | Full RFQ: every line's spec, match, price, compliance, question |
| GET | `/v1/rfqs/{id}/clarifications` | Open questions + a ready-to-send buyer email |
| PATCH | `/v1/rfqs/{id}/lines/{line_id}` | Apply a buyer answer: `{"answer": "2B"}`, or `{"qty": 24}`, `{"spec": {"finish": "2B"}}`, `{"selected_sku": "..."}`, `{"remove": true}` |
| POST | `/v1/rfqs/{id}/lines/{line_id}/approve` | Approve a matched line. Body optional: `{"sku": "...", "override_block": true, "note": "..."}` |
| POST | `/v1/rfqs/{id}/quotes/draft` | Quote JSON. `{"approved_only": true}` to include only approved lines |
| PUT | `/v1/catalog/items/{sku}` | Create/update a catalog item (partial fields OK) |
| GET | `/v1/catalog/items?q=` · `/v1/catalog/items/{sku}` | Browse the catalog |
| GET/POST | `/v1/samples` · `/v1/samples/{RFQ-01..04}` | Run a dataset sample RFQ in one click |
| GET | `/v1/eval` | Score against the answer key |
| GET | `/v1/traces?rfq_id=` | Agent run traces (what PRISM receives) |
| GET | `/v1/health` | Active LLM provider and PRISM status |

### Line shape (inside `GET /v1/rfqs/{id}` → `lines[]`)

```jsonc
{
  "line_id": "L2", "line_no": 2, "raw": "Stainless 304, 0.060 in, 48 x 96 -- 10 pcs",
  "qty": 10, "qty_ea": 10, "uom": "EA",
  "spec": {"material_family": "stainless steel", "grade": "304", "shape": "sheet", "finish": null,
           "thickness_in": 0.06, "gauge": 16, "width_in": 48, "length_in": 96, "standard": null, ...},
  "status": "MATCH | MATCH_ASSUMPTION | CLARIFY | NO_MATCH | REMOVED",
  "question": "For line 2 (...): which finish (#4, 2B, BA) do you need?",
  "options": [{"field": "finish", "choices": ["#4", "2B", "BA"]}],
  "candidates": ["SKU", ...], "selected_sku": "SKU", "selection_reason": "...",
  "item": {"sku", "description", "country_of_origin", "country_of_melt", "stock_qty", "lead_time_days", ...},
  "price": {"unit_price", "extended", "price_per_lb", "tier", "position": "below_median|above_range|...",
            "benchmark": {"low", "median", "high", "as_of", "source"}, "rationale": "$3.03/lb vs market ..."},
  "compliance": {"result": "OK | WARN | BLOCK", "flags": [{"rule_id": "CR-03", "severity": "BLOCK", "message": "..."}]},
  "assumptions": ["..."], "notes": ["..."], "duplicate_of": null, "approved": false, "history": []
}
```

RFQ-level: `summary` (counts, `quotable_value`, `open_questions`), `status` (`needs_clarification` / `ready_to_quote`), `requirements`, `clarification_email`, `warnings`, `trace`.

## LLM provider (swap with one env var)

`LLM_PROVIDER` = `claude` | `nicrron` | `openai` | `rules`. Default: `claude` if `ANTHROPIC_API_KEY` is set, else `rules`.

- **rules**: no model. Deterministic reader for text, email, PDF and spreadsheets. Images return 422.
- **claude**: official Anthropic SDK, `CLAUDE_MODEL` (default `claude-opus-5-5`). Reads images and scanned PDFs, extracts lines from free text, writes the buyer questions and email, and interprets free-text answers.
- **nicrron**: OpenAI SDK pointed at `https://api.nicrron.ai/v1` with `NICRRON_API_KEY`, model `NICRRON_MODEL`.

Whatever the provider, the numbers (gauge tables, unit conversions, matching, prices, compliance) come from the dataset rules, not the model.

Code: `rfq/providers/` (one file per provider), LLM tasks in `rfq/agent.py`.

## Block Convey PRISM

Set `PRISMTRACE_PROJECT_ID` and `PRISMTRACE_API_KEY` (and optionally `PRISMTRACE_HOST`). Each RFQ is a PRISM session: one agent-run trace with step spans (extract, parse, match_price_comply, clarify) plus one trace per LLM call. Without keys, the same records go to `var/traces.jsonl` and `GET /v1/traces`. Code: `rfq/tracing.py`.

## Data

The dataset is read from `../rudco_demo_data/` (override with `RUDCO_DATA_DIR`); all prices are synthetic. `backend/var/app.db` holds RFQs and the editable catalog, and `backend/var/traces.jsonl` the local traces. Both are git-ignored; delete `var/` to reset.
