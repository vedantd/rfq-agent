# `ai/` — Nicrron gateway + domain engine

**Owner:** AI / domain party.  
**Read first:** [docs/ai.md](../docs/ai.md) and shared [guardrails in root README](../README.md#team-guardrails).

- Live model client: `gateway.py`
- Match / price / compliance: `engine.py`

Do not add HTTP routes or HTML here. Keep `GatewayConfigurationError` / `GatewayResponseError` stable for the API layer.
