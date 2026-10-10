# `api/` — B2B REST + persistence

**Owner:** API / backend party.  
**Read first:** [docs/api.md](../docs/api.md) and shared [guardrails in root README](../README.md#team-guardrails).

- Routes and auth: `app.py`
- SQLite store: `store.py`
- Entrypoint: root `uvicorn app:app` (re-exports this package)

Do not put Nicrron prompts or match/price logic here — that belongs in `ai/`.
