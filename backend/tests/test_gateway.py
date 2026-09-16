from fastapi.testclient import TestClient

from app.config import load_settings
from app.engine.dispatch import set_fake_engine
from app.main import create_app

AUTH = {"Authorization": "Bearer test-proxy-key"}


def _client(hermes_root):
    return TestClient(create_app(load_settings()))


def test_v1_models_requires_bearer(hermes_root):
    client = _client(hermes_root)
    response = client.get("/v1/models")
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "invalid_request_error"


def test_v1_models_lists_aliases(hermes_root):
    client = _client(hermes_root)
    response = client.get("/v1/models", headers=AUTH)
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert "default" in ids
    assert "qoder" in ids
    assert "cursor" in ids
    assert "qoder/qmodel_38max" in ids
    assert "cursor/grok-4.6" in ids


def test_chat_text_via_fake_engine(hermes_root):
    set_fake_engine({"mode": "text", "text": "pong"})
    try:
        client = _client(hermes_root)
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"model": "default", "messages": [{"role": "user", "content": "ping"}]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["choices"][0]["message"]["content"] == "pong"
        assert body["model"] == "qoder/qmodel_38max"
    finally:
        set_fake_engine(None)


def test_chat_tool_calls_via_fake_engine(hermes_root):
    set_fake_engine({"mode": "tools", "calls": [{"name": "memory", "arguments": {"action": "add"}}]})
    try:
        client = _client(hermes_root)
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "model": "qoder/qmodel_38max",
                "messages": [{"role": "user", "content": "remember this"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {"name": "memory", "description": "store", "parameters": {"type": "object"}},
                    }
                ],
            },
        )
        assert response.status_code == 200
        message = response.json()["choices"][0]["message"]
        assert response.json()["choices"][0]["finish_reason"] == "tool_calls"
        assert message["content"] is None
        assert message["tool_calls"][0]["function"]["name"] == "memory"
        assert isinstance(message["tool_calls"][0]["function"]["arguments"], str)
    finally:
        set_fake_engine(None)


def test_chat_quota_maps_to_429(hermes_root):
    set_fake_engine({"mode": "error", "class": "quota"})
    try:
        client = _client(hermes_root)
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 429
        assert response.json()["error"]["type"] == "rate_limit_error"
    finally:
        set_fake_engine(None)


def test_chat_login_maps_to_401(hermes_root):
    set_fake_engine({"mode": "error", "class": "login"})
    try:
        client = _client(hermes_root)
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 401
        body = response.json()["error"]
        assert body["type"] == "invalid_request_error"
        assert "未登录" in body["message"]
    finally:
        set_fake_engine(None)


def test_chat_quota_message_is_readable(hermes_root):
    set_fake_engine({"mode": "error", "class": "quota"})
    try:
        client = _client(hermes_root)
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 429
        assert "额度" in response.json()["error"]["message"]
    finally:
        set_fake_engine(None)


def test_chat_empty_messages_400(hermes_root):
    client = _client(hermes_root)
    response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": []})
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"


def test_chat_illegal_model_400(hermes_root):
    client = _client(hermes_root)
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"model": "openai/gpt-4", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 400
