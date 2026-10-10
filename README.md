# RudCo QuotePilot — Live Nicrron B2B API + Single HTML Page

**Built for Track 2 (RudCo): RFQ → Quote.** The model calls are **real**, made from Python FastAPI over HTTPS via Nicrron's OpenAI-compatible gateway. **No simulated model responses, rule-only fallback, or client-side secrets.** Missing credentials, API failures, invalid model JSON, or ungrounded model responses result in visible 503/502 errors.

This is a hackathon-grade integration, not a production-ready quoting platform. The frontend is one file: [`frontend/index.html`](frontend/index.html) (HTML + CSS + vanilla JS, no npm required). The existing supplier catalog and benchmark values are explicitly **synthetic seeded examples**; customer-ready pricing needs sourced live supplier data.

## Repo layout (who edits what)

```
api/                 FastAPI routes, auth, SQLite          → docs/api.md
ai/                  Nicrron gateway + match/price engine  → docs/ai.md
frontend/            Single-page UI                        → docs/frontend.md
docs/                Party context from product requirements
rudco_demo_data/     Synthetic eval dataset (not runtime seed)
tests/               API tests (network stubbed only in tests)
examples/            Live smoke scripts
app.py               Thin entrypoint: uvicorn app:app
```

Start with [docs/STATUS.md](docs/STATUS.md) for **what works vs what’s missing**, then [docs/README.md](docs/README.md) for party ownership. Each folder also has a short `README.md` pointing at the right doc.

## Team guardrails

These keep parallel work from breaking the demo. Full detail is in the party docs.

| Rule | Applies to |
|---|---|
| Nicrron key only in local `.env` — never in HTML/JS or commits | Everyone |
| No fake model success path when Nicrron fails (503/502 only) | API, AI |
| Frontend may redesign visuals freely, but must keep calling the existing `/v1/*` contract with `X-API-Key` | Frontend |
| Keep required DOM ids and API paths listed in [docs/frontend.md](docs/frontend.md) unless API + frontend agree on a breaking change | Frontend |
| Do not recompute match/price/compliance in the browser — server response is source of truth | Frontend |
| Clarifications re-run `engine.analyze_line` only (no second model call) | API, AI |
| Quote draft stays blocked until every line is approved; synthetic prices → `demo_draft` | API, Frontend |
| Breaking response field renames need a heads-up + test update | API, AI |
| `pytest -q` must stay green before merge | Everyone |

Swagger at `/docs` is the live contract. If frontend and backend disagree, the OpenAPI schema and [docs/frontend.md](docs/frontend.md) win over ad-hoc UI experiments.

## Setup (macOS/Linux/Windows with bash)

```bash
git clone https://github.com/vedantd/rfq-agent.git
cd rfq-agent
python3 -m venv .venv
source .venv/bin/activate  # Windows Powershell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your **Nicrron account API key** (each teammate uses their own key locally):

```dotenv
NICRRON_API_KEY=sk-ncr-your-key-here
NICRRON_BASE_URL=https://api.nicrron.ai/v1
NICRRON_MODEL=nicrron/auto
```

**Never commit `.env`.** It is gitignored. Never paste API keys into chat, frontend JavaScript, commits, or public screenshots. The demo B2B header `X-API-Key: rudco-demo-key` is a *client-to-QuotePilot* sample key — it is **not** your Nicrron gateway credential. A Nicrron sponsor-credit promotion is listed on the hackathon resources page: `COLUMBIA26` (check current eligibility directly in your account).

Start:

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

- **Single-page UI:** http://127.0.0.1:8000/
- **Swagger / REST API docs:** http://127.0.0.1:8000/docs
- **Configuration status:** http://127.0.0.1:8000/health
- **Actual live API call:** click **Test live model call** in UI, or run:

```bash
curl -X POST http://127.0.0.1:8000/v1/gateway/test \
  -H 'X-API-Key: rudco-demo-key'
```

The `connected:true` result is returned **only after an actual model completion returns successfully**. `/health` intentionally does **not** imply network connectivity.

## End-to-end hackathon demo

1. Enter RFQ text or upload `.txt`, `.eml`, `.pdf`, `.csv` or `.xlsx` (text PDFs only; scanned PDFs need OCR).
2. Click **Process with real AI gateway**. FastAPI sends the RFQ to Nicrron, receives LLM-generated structured JSON, validates response schema and source quotes, normalizes common units, and performs deterministic matching and pricing.
3. First seeded line matches `SS-304-16GA-4896` and gets a $245/sheet **illustrative demo price**. Second line lacks grade and dimensions and is blocked.
4. Supply grade `316`, width `48`, length `96` for the second line; click **Apply clarification & revalidate**.
5. Approve both lines, then click **Generate quote JSON**. The resulting quote is flagged `demo_draft`, **not** `ready_to_send`, because prices are seeded examples.

If your RFQ is different from the example, only exact catalog matches will price; other items remain blocked until you add SKUs via the Catalog API. This is intentional: the system will not invent inventory or substitute a different grade.

## B2B REST API overview

| Method | Endpoint | Function |
|---|---|---|
| `POST` | `/v1/gateway/test` | **Real** model call via Nicrron |
| `POST` | `/v1/rfqs` | Submit text RFQ, invoke model, return analyzed lines |
| `POST` | `/v1/rfqs/upload` | Upload text-based PDF, email, CSV or XLSX |
| `GET` | `/v1/rfqs/{id}` | Read RFQ + catalog/price/compliance decisions |
| `GET` | `/v1/rfqs/{id}/clarifications` | Buyer clarification questions |
| `PATCH` | `/v1/rfqs/{id}/lines/{line_id}` | Apply field clarifications (server re-evaluates) |
| `POST` | `/v1/rfqs/{id}/lines/{line_id}/approve` | Human approval only when all blockers resolved |
| `POST` | `/v1/rfqs/{id}/quotes/draft` | Quote JSON, requires all lines approved |
| `GET` | `/v1/catalog/items` | View supplier catalog |
| `PUT` | `/v1/catalog/items/{sku}` | Add/update supplied catalog SKU |

**B2B auth:** `X-API-Key: rudco-demo-key` is a known sample *client-to-QuotePilot* key, NOT the model gateway credential. Two scoped demo tenants are provided; replace keys and use proper key management before deployment.

### Example

```bash
curl -X POST http://127.0.0.1:8000/v1/rfqs \
 -H 'X-API-Key: rudco-demo-key' \
 -H 'Content-Type: application/json' \
 -d '{"buyer_id":"ACME-001","source_type":"email","text":"Need 20 sheets 304 SS 16ga 4x8, mill certs required. Also 10 sheets stainless 1/8 inch."}'
```

The response contains `parser_mode: nicrron_live` and `gateway: {mode: live_gateway, model: ..., latency_ms: ...}` only when the gateway actually completed the model extraction.

## Design/implementation decisions

- **Actual gateway connection:** [`ai/gateway.py`](ai/gateway.py) makes an authenticated `httpx` POST to `https://api.nicrron.ai/v1/chat/completions` with your bearer key, model name and chat messages. Direct REST avoids the OpenAI SDK dependency. No remote response is fabricated.
- **Structured extraction:** Prompt requires a `lines` JSON object. Pydantic validates fields and checks each `raw_text` is an exact substring of the original RFQ. Deterministic parsing is used as a verification and normalization layer, not as an alternative model provider.
- **Uncertainty:** Missing specs result in `needs_clarification`, not guessed attributes; wrong standards or no verified catalog SKU block matching.
- **Pricing:** Supplier cost × (1 + configurable fixed markup), with explicit synthetic benchmark source and price explanation. No unsupported live market claims.
- **Compliance:** Checks requested MTR/COO information against supplier records. Catalog statements are not independently verified certifications.
- **Review:** Requires human approval before drafting a quote. No real email is sent to buyers without an external configured webhook.
- **Storage:** Local SQLite demo DB, tenant-scoped reads and catalog, no production concurrency/disaster recovery promises.

## Test

```bash
pytest -q
```

Tests stub network calls **only inside tests** to verify API behavior and request configuration, and do not claim that an authenticated production gateway request succeeded. After adding your real Nicrron key, run `bash examples/live_request.sh` to perform the real smoke test.

## What remains for a deployable B2B product

Real supplier price feeds and certification evidence, persistent background jobs/retries, stronger authentication and audit controls, SSRF-safe outbound webhook configuration, and production tenancy/security. Observability was intentionally excluded from this version as requested.

### Optional Docker launch

```bash
docker build -t rudco-quotepilot .
docker run --rm -p 8000:8000 --env-file .env rudco-quotepilot
```

If exposed outside localhost, replace the demo B2B API keys and add TLS, authentication, request throttling, and stronger abuse protections first.
