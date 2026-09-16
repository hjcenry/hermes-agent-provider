from app.engine.dispatch import run_engine, set_fake_engine
from app.engine.types import EngineResult


def test_dispatch_uses_cursor_runner_when_no_fake(monkeypatch):
    set_fake_engine(None)
    called = {}

    def fake_run(prompt, *, model, cwd, timeout_sec, max_turns):
        called["prompt"] = prompt
        called["model"] = model
        return EngineResult(ok=True, text="from-cursor", engine="cursor", model=model)

    monkeypatch.setattr("app.adapters.cursor.runner.run_cursor", fake_run)
    result = run_engine("hello", engine="cursor", model="grok-4.6")
    assert result.text == "from-cursor"
    assert called["model"] == "grok-4.6"
    assert called["prompt"] == "hello"
