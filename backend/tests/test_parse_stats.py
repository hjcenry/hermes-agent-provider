from fastapi.testclient import TestClient

from app.config import load_settings
from app.engine.dispatch import set_fake_engine
from app.main import create_app
from app.translator.parse import parse_output
from app.translator.stats import public_parse_stats, record_parse, reset_parse_stats

AUTH = {"Authorization": "Bearer test-proxy-key"}


def test_record_parse_counts_fence_and_degraded():
    reset_parse_stats()
    ok = parse_output(
        '```hermes-proxy\n{"type":"tool_calls","calls":[{"name":"memory","arguments":{}}]}\n```',
        tool_names=["memory"],
    )
    bad = parse_output(
        '```hermes-proxy\n{"type":"tool_calls","calls":[{"name":"nope","arguments":{}}]}\n```',
        tool_names=["memory"],
    )
    record_parse(ok)
    record_parse(bad)
    stats = public_parse_stats()
    assert stats["counts"] == {"fence_ok": 1, "text": 0, "degraded": 1}
    assert stats["last"]["kind"] == "degraded"
    assert stats["last"]["label"] == "降级文本"


def test_parse_stats_api_requires_cookie_and_updates_after_v1(hermes_root):
    reset_parse_stats()
    set_fake_engine({"mode": "tools", "calls": [{"name": "memory", "arguments": {"action": "add"}}]})
    try:
        client = TestClient(create_app(load_settings()))
        assert client.get("/api/parse-stats").status_code == 401
        assert client.post("/api/login", json={"username": "admin", "password": "admin"}).status_code == 200
        empty = client.get("/api/parse-stats")
        assert empty.status_code == 200
        assert empty.json()["counts"]["fence_ok"] == 0
        chat = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "记住我叫测试"}],
                "tools": [{"type": "function", "function": {"name": "memory", "parameters": {"type": "object"}}}],
            },
        )
        assert chat.status_code == 200
        stats = client.get("/api/parse-stats").json()
        assert stats["counts"]["fence_ok"] == 1
        assert stats["last"]["kind"] == "tool_calls"
        assert "memory" in stats["last"]["tools"]
    finally:
        set_fake_engine(None)
        reset_parse_stats()
