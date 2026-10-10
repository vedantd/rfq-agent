# Overview — product & hackathon context

## What this product is

**RudCo QuotePilot** (Track 2: RFQ → Quote) turns messy buyer requests into review-gated, explainable quote drafts.

Flow: ingest RFQ → **live Nicrron extraction** → deterministic catalog match / pricing / compliance → buyer clarifications → human approval → quote JSON.

## Requirements that drive every edit

1. **Real model calls only.** FastAPI talks to Nicrron over HTTPS (`ai/gateway.py`). Missing keys, API failures, bad JSON, or ungrounded extractions must surface as 503/502 — never invent a success path.
2. **Evidence-backed extraction.** Each model line’s `raw_text` and evidence must be grounded in the original RFQ; the server validates this.
3. **Uncertainty over guessing.** Missing grade/dimensions → `needs_clarification`, not invented specs. Wrong or unverified SKUs block matching.
4. **Explainable pricing.** Supplier cost × fixed markup; synthetic benchmarks must be labeled. No unsupported live-market claims.
5. **Review gate.** All lines approved before `/quotes/draft`. No buyer email send without a configured integration webhook.
6. **Hackathon-grade storage.** Local SQLite, tenant-scoped by demo API keys — not production multi-tenant infra.

## Repo map

```
api/           REST surface + persistence
ai/            Nicrron + domain engine
frontend/      Single HTML workspace
docs/          Party-specific context (you are here)
rudco_demo_data/  Synthetic eval dataset (separate from runtime seed catalog)
tests/         API behavior tests (network stubbed only in tests)
examples/      Live smoke scripts against a running server
```

## Run (all parties)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set NICRRON_API_KEY
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

- UI: http://127.0.0.1:8000/
- Swagger: http://127.0.0.1:8000/docs
- Live smoke: `bash examples/live_request.sh`

## Demo narrative (judges)

1. Sample RFQ: 304 16ga 4×8 matches seeded SKU; second stainless line needs grade/size.
2. Clarify → revalidate → approve → draft quote flagged `demo_draft` (not `ready_to_send`).
3. Point at `parser_mode: nicrron_live` and gateway latency in the response.
