#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST http://127.0.0.1:8000/v1/gateway/test -H 'X-API-Key: rudco-demo-key' | python -m json.tool
curl -sS -X POST http://127.0.0.1:8000/v1/rfqs \
  -H 'X-API-Key: rudco-demo-key' -H 'Content-Type: application/json' \
  -d '{"buyer_id":"ACME","text":"Need 20 sheets 304 SS 16ga 4x8, mill certs required. Also 10 sheets stainless 1/8 inch."}' | python -m json.tool
