"""PRISM wrapper: no-op without credentials, images never sent, errors never raised into the quote path."""
from ai import prism


def test_noop_without_credentials():
    assert prism.configured() is False and prism.status()["enabled"] is False
    prism.trace_llm(model="m", messages=[{"role": "user", "content": "x"}], output="y", latency_ms=1)
    with prism.session("rfq_test") as sid:
        assert sid is None
    prism.flush()


def test_images_are_replaced_and_text_truncated():
    flat = prism._flatten([{"role": "user", "content": [
        {"type": "text", "text": "Extract lines"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
        {"role": "system", "content": "z" * 30_000}])
    assert flat[0]["content"] == "Extract lines\n[image]" and "base64" not in str(flat)
    assert len(flat[1]["content"]) == prism.MAX_CHARS


def test_trace_sends_session_and_never_raises(monkeypatch):
    monkeypatch.setenv("PRISMTRACE_API_KEY", "pt-test")
    monkeypatch.setenv("PRISMTRACE_PROJECT_ID", "proj")
    sent = []

    class Fake:
        def trace_llm(self, **kw):
            sent.append(kw)

        def flush(self, timeout=2.0):
            raise RuntimeError("network down")

    monkeypatch.setattr(prism, "_client", Fake())
    with prism.session("rfq_abc"):
        prism.trace_llm(model="nicrron/fastest", messages=[{"role": "user", "content": "hi"}], output="ok",
                        latency_ms=5, purpose="rfq_extract", usage={"prompt_tokens": 3, "completion_tokens": 1})
        prism.flush()   # a failing flush is swallowed
    assert sent[0]["session_id"] == "rfq_abc" and sent[0]["agent_id"] == "quotepilot-nicrron"
    assert sent[0]["metadata"]["purpose"] == "rfq_extract" and sent[0]["token_count_input"] == 3

    class Broken:
        def trace_llm(self, **kw):
            raise RuntimeError("boom")

    monkeypatch.setattr(prism, "_client", Broken())
    prism.trace_llm(model="m", messages=[], output="", latency_ms=0, error="Nicrron HTTP 500")
