"""Keep tests offline: PRISM tracing is switched off so no test POSTs to PRISM or uses its client."""
import pytest

from ai import prism


@pytest.fixture(autouse=True)
def no_prism(monkeypatch):
    for name in ("PRISMTRACE_API_KEY", "PRISMTRACE_PROJECT_ID", "PRISMTRACE_HOST"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(prism, "_client", None)
    yield
