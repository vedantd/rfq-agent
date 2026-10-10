# API party — `api/`

You own the B2B HTTP surface, auth, uploads, persistence, and webhook dispatch. You do **not** own Nicrron prompts or catalog-matching math — those live in `ai/`.

## Requirements in your context

| Requirement | How the API enforces it |
|---|---|
| Real Nicrron only | Call `ai.gateway.extract_live` / `test_connection`; map config errors → **503**, response errors → **502**. Never catch and fabricate lines. |
| Tenant isolation | `X-API-Key` → tenant via `QUOTEPILOT_API_KEYS` JSON. Demo keys: `rudco-demo-key`, `partner-demo-key`. |
| Review gate | `/quotes/draft` returns **409** until every line is `approved`. |
| No fake email | Clarification dispatch needs `QUOTEPILOT_WEBHOOK_URL` + `SECRET`; otherwise **412**. Never claim buyer email was sent. |
| Upload limits | 5MB; text PDFs / eml / csv / xlsx only. Empty OCR-less scans → **422**. |
| Idempotency | Optional `Idempotency-Key` on `POST /v1/rfqs`. |

## Files

| File | Role |
|---|---|
| [`api/app.py`](../api/app.py) | FastAPI app, Pydantic request models, all `/v1/*` routes, serves `frontend/index.html` at `/` |
| [`api/store.py`](../api/store.py) | SQLite RFQs / quotes / per-tenant catalog (`RFQ_DB_PATH`) |

Root [`app.py`](../app.py) is a thin re-export so `uvicorn app:app` still works.

## Endpoints you maintain

| Method | Path | Notes |
|---|---|---|
| `GET` | `/` | Serves frontend HTML (no secrets) |
| `GET` | `/health` | Config status only — not connectivity |
| `POST` | `/v1/gateway/test` | Real model ping |
| `POST` | `/v1/rfqs`, `/v1/rfqs/upload` | Ingest + live extract |
| `GET` | `/v1/rfqs/{id}` | Summarized RFQ |
| `GET/PATCH` | clarifications / lines | Clarifications re-run **engine** only (no new model call) |
| `POST` | `.../approve`, `.../quotes/draft` | Human review + quote JSON |
| `GET/PUT` | `/v1/catalog/items` | Tenant catalog |

## Collaboration boundaries

- **AI party:** change prompts, extraction schema, `analyze_line` / pricing — you only wire results into responses and storage.
- **Frontend party:** they call your routes with `X-API-Key`. Do not put Nicrron keys in responses. If you rename paths or response fields, update [frontend.md](frontend.md) and coordinate before merge — wild UI redesigns must still hit this contract.
- **Tests:** [`tests/test_live_api.py`](../tests/test_live_api.py) stubs `ai.gateway._completion` only inside tests; keep that contract if you rename helpers.

## Local check

```bash
pytest -q
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```
