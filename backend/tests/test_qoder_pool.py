from types import SimpleNamespace

from app.adapters.qoder import runner
from app.engine.types import EngineResult


class AssistantMessage:
    def __init__(self, text: str):
        self.content = [SimpleNamespace(text=text)]


class ResultMessage:
    def __init__(self, text: str):
        self.session_id = "q-1"
        self.is_error = False
        self.errors = []
        self.result = text


class _FakeAgen:
    def __init__(self, prompt: str):
        self.prompt = prompt
        self.closed = False

    async def __aiter__(self):
        yield AssistantMessage(f"echo:{self.prompt}")
        yield ResultMessage(f"echo:{self.prompt}")

    async def aclose(self):
        self.closed = True


class _FakeClient:
    connects = 0
    queries = 0

    def __init__(self, options=None, transport=None):
        self._prompt = ""

    async def connect(self, prompt=None):
        _FakeClient.connects += 1

    async def query(self, prompt, **kwargs):
        _FakeClient.queries += 1
        self._prompt = prompt

    async def receive_response(self):
        yield AssistantMessage(f"echo:{self._prompt}")
        yield ResultMessage(f"echo:{self._prompt}")

    async def disconnect(self):
        return None


def _fake_query(*, prompt, options=None, transport=None):
    _fake_query.calls.append(prompt)
    return _FakeAgen(prompt)


_fake_query.calls = []


def _patch_common(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "describe_qoder", lambda: {"ok": True, "installed": True})
    monkeypatch.setattr(runner, "_qoder_options", lambda cwd, model, max_turns: object())
    monkeypatch.setattr(runner, "query", _fake_query)
    monkeypatch.setattr(runner, "QoderSDKClient", _FakeClient)


def test_qoder_pool_reuses_worker_thread(monkeypatch, tmp_path):
    _fake_query.calls = []
    _FakeClient.connects = 0
    _FakeClient.queries = 0
    runner.reset_qoder_pool()
    _patch_common(monkeypatch, tmp_path)

    first = runner.run_qoder("hi", model="qmodel_38max", cwd=tmp_path, timeout_sec=10, max_turns=1)
    thread = runner._POOL._thread
    second = runner.run_qoder("again", model="qmodel_38max", cwd=tmp_path, timeout_sec=10, max_turns=1)

    assert first.ok and first.text.startswith("echo:")
    assert second.ok and "again" in second.text
    assert _fake_query.calls == ["hi"]
    assert _FakeClient.queries == 1
    assert _FakeClient.connects >= 1
    assert thread is not None and thread is runner._POOL._thread and thread.is_alive()
    runner.reset_qoder_pool()


def test_qoder_warmup_uses_idle_client_for_first_turn(monkeypatch, tmp_path):
    _fake_query.calls = []
    _FakeClient.connects = 0
    _FakeClient.queries = 0
    runner.reset_qoder_pool()
    _patch_common(monkeypatch, tmp_path)

    runner.warmup_qoder(tmp_path, model="qmodel_38max", max_turns=1)
    runner._POOL._submit(runner._POOL._ensure_idle(tmp_path, "qmodel_38max", 1), 5)

    result = runner.run_qoder("remember", model="qmodel_38max", cwd=tmp_path, timeout_sec=10, max_turns=1)
    assert result.ok and "remember" in result.text
    assert _FakeClient.connects >= 1
    assert _FakeClient.queries == 1
    assert _fake_query.calls == []
    runner.reset_qoder_pool()
