from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


def _client(hermes_root):
    return TestClient(create_app(load_settings()))


def test_engines_status_requires_login(hermes_root, monkeypatch):
    monkeypatch.setattr("app.adapters.qoder.account.public_qoder_status", lambda refresh=False: {"ok": False, "engine": "qoder"})
    client = _client(hermes_root)
    response = client.get("/api/engines/status")
    assert response.status_code == 401


def test_login_then_engines_status_includes_qoder(hermes_root, monkeypatch):
    monkeypatch.setattr(
        "app.adapters.qoder.account.public_qoder_status",
        lambda refresh=False: {
            "ok": True,
            "engine": "qoder",
            "quota": {"exceeded": False, "text": "套餐内 剩余 90 / 100"},
            "account": {"id": "u", "type": "pro", "label": "u"},
        },
    )
    monkeypatch.setattr(
        "app.adapters.cursor.account.public_cursor_status",
        lambda refresh=False: {"ok": False, "engine": "cursor", "fallback_reason": "not_logged_in"},
    )
    client = _client(hermes_root)
    denied = client.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert denied.status_code == 401
    login = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200
    assert login.json()["user"]["username"] == "admin"
    status = client.get("/api/engines/status")
    assert status.status_code == 200
    body = status.json()
    assert body["qoder"]["engine"] == "qoder"
    assert body["qoder"]["quota"]["text"]
    assert body["active"] == "qoder"
    assert body["cursor"]["engine"] == "cursor"
    assert body["cursor"]["fallback_reason"] != "not_implemented"
