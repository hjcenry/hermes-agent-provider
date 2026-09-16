from pathlib import Path
from types import SimpleNamespace

from app.adapters.cursor import runner
from app.engine.types import EngineResult


class _FakeRun:
    def __init__(self, text: str):
        self._text = text

    async def stream(self):
        yield SimpleNamespace(type="assistant", message=SimpleNamespace(content=[SimpleNamespace(text=self._text)]))

    async def wait(self):
        return SimpleNamespace(status="ok", result=self._text)


class _FakeAgent:
    creates = 0

    def __init__(self, text: str):
        self.agent_id = "agent-1"
        self._text = text

    @classmethod
    async def create(cls, options, client=None):
        cls.creates += 1
        return cls("pong")

    async def send(self, prompt: str):
        return _FakeRun(f"echo:{prompt}")

    async def close(self):
        return None


class _FakeClient:
    launches = 0

    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


async def _fake_launch(cwd: str):
    _FakeClient.launches += 1
    return _FakeClient()


def test_cursor_pool_reuses_bridge(monkeypatch, tmp_path):
    _FakeClient.launches = 0
    _FakeAgent.creates = 0
    runner.reset_cursor_pool()
    monkeypatch.setattr(runner, "describe_cursor", lambda: {"ok": True, "installed": True})
    monkeypatch.setattr(runner, "cursor_api_key", lambda: "key")
    monkeypatch.setattr(runner, "_options", lambda cwd, model: object())
    monkeypatch.setattr(runner, "_launch_bridge", _fake_launch)
    monkeypatch.setattr(runner, "AsyncAgent", _FakeAgent)

    first = runner.run_cursor("hi", model="grok-4.6", cwd=tmp_path, timeout_sec=10, max_turns=1)
    second = runner.run_cursor("again", model="grok-4.6", cwd=tmp_path, timeout_sec=10, max_turns=1)
    assert first.ok and first.text.startswith("echo:")
    assert second.ok and "again" in second.text
    assert _FakeClient.launches == 1
    assert _FakeAgent.creates == 2
    runner.reset_cursor_pool()
