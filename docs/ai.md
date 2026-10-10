# AI party — `ai/`

You own live model extraction and the deterministic domain engine (match, price, compliance, clarifications). You do **not** own HTTP routing or the HTML UI.

## Requirements in your context

| Requirement | How AI code enforces it |
|---|---|
| Real Nicrron calls | [`gateway.py`](../ai/gateway.py) POSTs to `{NICRRON_BASE_URL}/chat/completions` with bearer key. No OpenAI SDK; no fabricated completions. |
| Structured + grounded JSON | Prompt requires `lines[]` with exact `raw_text` substrings and evidence. Pydantic validates; ungrounded fields are rejected. |
| Rules as verification, not fallback | `engine.extract_rule_line` may normalize units / help validation — it must **not** replace a failed live call at runtime. |
| No invention | Missing grade/size → clarifications. No invented SKUs, standards, certs, or prices. |
| Explainable pricing | Cost × markup; attach synthetic benchmark labels. Clarification patches re-run `analyze_line` without a second model call. |

## Files

| File | Role |
|---|---|
| [`ai/gateway.py`](../ai/gateway.py) | Env config, `_completion`, `extract_live`, `test_connection`, system prompt, model schema |
| [`ai/engine.py`](../ai/engine.py) | Seed catalog, gauge/unit helpers, `analyze_line`, pricing, compliance, `summarize` |

## Env vars you care about

```dotenv
NICRRON_API_KEY=...
NICRRON_BASE_URL=https://api.nicrron.ai/v1
NICRRON_MODEL=nicrron/auto
NICRRON_TIMEOUT_SECONDS=40
```

`/health` reports `configured`; only `POST /v1/gateway/test` proves connectivity.

## Collaboration boundaries

- **API party:** they call `extract_live` and map exceptions. Keep `GatewayConfigurationError` / `GatewayResponseError` stable.
- **Frontend party:** they display `parser_mode`, gateway latency, blockers, and clarification fields you put on each line — keep those fields stable or coordinate.
- **Demo data party:** [`rudco_demo_data/`](../rudco_demo_data/) is a richer synthetic eval set; the runtime seed catalog today lives in `engine.sample_catalog`. Align SKUs carefully if you wire them together.

## Local check

```bash
# server running with real key
curl -sS -X POST http://127.0.0.1:8000/v1/gateway/test \
  -H 'X-API-Key: rudco-demo-key' | python3 -m json.tool
# expect connected: true
pytest -q   # stubs network; still verifies request shape + quote flow
```

## Prompt / schema change checklist

1. Update `SYSTEM_PROMPT` and `ModelLine` together.
2. Keep “exact substring” grounding rules.
3. Extend `engine.analyze_line` if new fields affect match/price/compliance.
4. Update tests’ `FAKE_GATEWAY_JSON` fixtures.
