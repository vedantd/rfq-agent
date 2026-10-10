# Frontend party — `frontend/`

You own the single-page RFQ workspace UI. You do **not** own Nicrron keys, extraction prompts, matching, pricing, or SQLite.

## Requirements in your context

| Requirement | How the frontend must behave |
|---|---|
| No client-side secrets | Never embed `NICRRON_API_KEY`. Only the demo B2B header `X-API-Key` (user-entered) goes to our FastAPI. |
| Real gateway only | Surface 502/503 errors from the API. Do not invent “connected” or mock RFQ lines in the browser. |
| Server is source of truth | After clarify/approve, re-fetch or use the API response — do not recompute match/price/compliance in JS. |
| Review gate | Keep **Generate quote** disabled until the API says all lines are approved; show 409 detail if draft fails. |
| Upload contract | Send files to `POST /v1/rfqs/upload` as `multipart/form-data` with `file` + `buyer_id` (optional `buyer_email`). |

## Files

| File | Role |
|---|---|
| [`frontend/index.html`](../frontend/index.html) | HTML + CSS + vanilla JS (no npm). Served by FastAPI at `/`. |

## Guardrails — UI can change; contract cannot

You may redesign layout, typography, motion, and copy **as long as** you keep these stable:

### Required DOM ids (JS depends on them)

`buyer`, `demo-key`, `raw-rfq`, `process`, `file`, `file-name`, `notice`, `test-gateway`, `gateway-badge`, `gateway-detail`, `rfq-output`, `create-quote`, `quote-output`

If you rename an id, update the JS in the same file and keep `tests/test_live_api.py::test_frontend_is_single_file` green (it asserts key UI strings).

### Required API calls (do not invent alternate paths)

| UI action | Method + path | Auth |
|---|---|---|
| Health badge | `GET /health` | none |
| Test live model | `POST /v1/gateway/test` | `X-API-Key` |
| Process text RFQ | `POST /v1/rfqs` JSON `{buyer_id, text, source_type}` | `X-API-Key` |
| Upload RFQ | `POST /v1/rfqs/upload` FormData | `X-API-Key` |
| Refresh RFQ | `GET /v1/rfqs/{id}` | `X-API-Key` |
| Clarify line | `PATCH /v1/rfqs/{id}/lines/{line_id}` JSON fields | `X-API-Key` |
| Approve line | `POST /v1/rfqs/{id}/lines/{line_id}/approve` | `X-API-Key` |
| Draft quote | `POST /v1/rfqs/{id}/quotes/draft` | `X-API-Key` |

Clarification body fields the backend accepts: `material`, `form`, `grade`, `thickness_in`, `width_in`, `length_in`, `quantity`, `standard_required`. Numbers for inch/qty fields.

### Response fields you should keep rendering

- RFQ: `rfq_id`, `parser_mode`, `gateway.model`, `gateway.latency_ms`, `lines[]`
- Line: `id`, `raw_text`, `status`, `blockers`, `clarifications`, `match`, `pricing`, `compliance`
- Quote: `id`, `ready_to_send`, `grand_total_usd`, `warnings`, full JSON for copy

If the API party renames these, they must update you — do not invent parallel shapes in the browser.

### Hard no’s

- No `fetch` to `api.nicrron.ai` from the browser.
- No local fake catalog / pricing math.
- No claiming email was sent to the buyer.
- No npm / build step unless the whole team agrees (current contract: one HTML file).

## Collaboration boundaries

- **API party:** OpenAPI at `/docs` is the contract. Propose breaking path/body changes in chat before merging.
- **AI party:** Line statuses and clarification questions come from the engine; display them, don’t reinterpret.

## Local check

```bash
# with server running
curl -s http://127.0.0.1:8000/ | head -c 200   # HTML served
pytest -q tests/test_live_api.py::test_frontend_is_single_file
```

Open http://127.0.0.1:8000/ — click **Test live model call**, then **Process with real AI gateway** on the sample RFQ.
