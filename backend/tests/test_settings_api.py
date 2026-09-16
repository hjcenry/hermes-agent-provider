from fastapi.testclient import TestClient

from app.config import load_settings
from app.engine.dispatch import set_fake_engine
from app.main import create_app

AUTH = {"Authorization": "Bearer test-proxy-key"}


def _client(hermes_root):
    return TestClient(create_app(load_settings()))


def _login(client: TestClient) -> None:
    response = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200


def test_settings_requires_cookie_not_bearer(hermes_root):
    client = _client(hermes_root)
    response = client.get("/api/settings", headers=AUTH)
    assert response.status_code == 401


def test_get_put_settings_writes_local_and_reloads(hermes_root):
    client = _client(hermes_root)
    _login(client)
    got = client.get("/api/settings")
    assert got.status_code == 200
    body = got.json()
    assert body["engine"] == "qoder"
    assert body["models"]["cursor"] == "grok-4.6"
    assert body["timeout_sec"] == 180
    assert body["max_concurrency"] == 2
    assert body["base_url"].endswith("/v1")
    assert body["proxy_key_hint"].endswith("-key")
    assert "test-proxy-key" not in body["proxy_key_hint"]

    saved = client.put(
        "/api/settings",
        json={
            "engine": "cursor",
            "models": {"qoder": "qmodel_38max", "cursor": "composer-2.5"},
            "workspace": "data/ws2",
            "timeout_sec": 90,
            "max_concurrency": 1,
            "max_turns": 3,
        },
    )
    assert saved.status_code == 200
    again = client.get("/api/settings").json()
    assert again["engine"] == "cursor"
    assert again["models"]["cursor"] == "composer-2.5"
    assert again["timeout_sec"] == 90
    assert again["max_concurrency"] == 1
    text = (hermes_root / "config" / "local.yaml").read_text(encoding="utf-8")
    assert "composer-2.5" in text
    assert "timeout_sec: 90" in text


def test_put_active_engine_changes_status_and_default_v1(hermes_root, monkeypatch):
    monkeypatch.setattr("app.adapters.qoder.account.public_qoder_status", lambda refresh=False: {"ok": False, "engine": "qoder"})
    monkeypatch.setattr("app.adapters.cursor.account.public_cursor_status", lambda refresh=False: {"ok": False, "engine": "cursor"})
    set_fake_engine({"mode": "text", "text": "pong"})
    try:
        client = _client(hermes_root)
        _login(client)
        switched = client.put("/api/engines/active", json={"engine": "cursor"})
        assert switched.status_code == 200
        assert client.get("/api/engines/status").json()["active"] == "cursor"
        chat = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"model": "default", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert chat.status_code == 200
        assert chat.json()["model"] == "cursor/grok-4.6"
    finally:
        set_fake_engine(None)


def test_engines_models_lists_cursor_catalog(hermes_root):
    client = _client(hermes_root)
    _login(client)
    response = client.get("/api/engines/models", params={"engine": "cursor"})
    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["items"]]
    assert body["engine"] == "cursor"
    assert body["default"] == "grok-4.6"
    assert "grok-4.6" in ids
    assert "claude-opus-5" in ids


def test_hermes_snippet_masks_proxy_key(hermes_root):
    client = _client(hermes_root)
    _login(client)
    response = client.get("/api/hermes-snippet")
    assert response.status_code == 200
    text = response.json()["text"]
    assert "YOUR_PROXY_API_KEY" in text
    assert "test-proxy-key" not in text
    assert "chat_completions" in text
    assert "127.0.0.1:8765/v1" in text
    assert "provider: custom" in text
