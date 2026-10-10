# Docs index — who owns what

This repo is split so each working group can edit with clear boundaries. Read **your** doc before changing code in that folder. All parties should skim [overview.md](overview.md) once.

| Party | Folder | Doc | Owns |
|---|---|---|---|
| Product / hackathon | — | [overview.md](overview.md) | Track goals, demo narrative, non-goals |
| API / backend | [`api/`](../api/) | [api.md](api.md) | FastAPI routes, auth, SQLite, webhooks |
| AI / domain | [`ai/`](../ai/) | [ai.md](ai.md) | Nicrron gateway, extraction, match/price/compliance |
| Frontend | [`frontend/`](../frontend/) | [frontend.md](frontend.md) | Single-page RFQ workspace UI |
| Demo data | [`rudco_demo_data/`](../rudco_demo_data/) | [../rudco_demo_data/README.md](../rudco_demo_data/README.md) | Synthetic catalog, RFQs, benchmarks |

**Hard rules shared by everyone**

- Nicrron credentials live only in local `.env` (never frontend, never commits).
- No simulated model responses or rules-only runtime fallback when the live gateway fails.
- Prices and supplier records in the seeded catalog are synthetic; quotes stay `demo_draft` until real supplier data exists.
- Human approval is required before drafting a quote.

**Cross-party guardrails (short)**

- Frontend may redesign the UI, but must keep calling the existing `/v1/*` contract with `X-API-Key` — see [frontend.md](frontend.md).
- API/AI may evolve internals, but breaking response fields or paths needs a heads-up to frontend + a test update.
- Full list lives in the root [README — Team guardrails](../README.md#team-guardrails).
