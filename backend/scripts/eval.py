"""Run the answer-key eval and print a line-by-line table.  Usage: uv run python scripts/eval.py [--fails]"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LLM_PROVIDER", "rules")

from rfq import store  # noqa: E402
from rfq.evaluation import run_eval  # noqa: E402

store.init()
res = run_eval()
only_fails = "--fails" in sys.argv
for r in res["rows"]:
    bad = not r["status_ok"] or r["sku_ok"] is False or r["compliance_ok"] is False
    if only_fails and not bad:
        continue
    mark = "FAIL" if bad else " ok "
    print(f"[{mark}] {r['rfq']} L{r['line']}: {r['raw'][:55]:55} | status {r['status']:16} (exp {r['expected_status']}) "
          f"| sku {r['selected_sku']} {'' if r['sku_ok'] in (None, True) else '(exp ' + '/'.join(r['expected_skus']) + ')'} "
          f"| comp {r['compliance']} (exp {r['expected_compliance']})")
print()
for k in ("status", "sku", "compliance", "asks_when_it_should"):
    v = res[k]
    print(f"{k:22} {v['correct']}/{v['total']}  ({v['rate']})")
print(f"guessed_instead_of_asking  {res['guessed_instead_of_asking']}")
