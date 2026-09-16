from app.engine.dispatch import run_engine, set_fake_engine
from app.engine.types import EngineResult



def test_dispatch_uses_qoder_runner_when_no_fake(monkeypatch):
    set_fake_engine(None)
    called = {}

    def fake_run(prompt, *, model, cwd, timeout_sec, max_turns):
        called["prompt"] = prompt
        called["model"] = model
        return EngineResult(ok=True, text="from-qoder", engine="qoder", model=model)

    monkeypatch.setattr("app.adapters.qoder.runner.run_qoder", fake_run)
    result = run_engine("hello", engine="qoder", model="qmodel_38max")
    assert result.text == "from-qoder"
    assert called["model"] == "qmodel_38max"
    assert called["prompt"] == "hello"


