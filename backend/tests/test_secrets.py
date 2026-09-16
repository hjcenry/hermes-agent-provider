from fastapi.testclient import TestClient

from app.config import get_settings, load_settings
from app.main import create_app
from app.settings_io import apply_secret_updates, hermes_connect, upsert_secrets


def _client(hermes_root):
    return TestClient(create_app(load_settings()))


def _login(client: TestClient) -> None:
    response = client.post("/api/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200


def test_upsert_secrets_keeps_comments_and_other_keys(tmp_path):
    path = tmp_path / "secrets.env"
    path.write_text("# keep me\nPROXY_API_KEY=old\nSESSION_SECRET=stay\n", encoding="utf-8")
    upsert_secrets(path, {"PROXY_API_KEY": "new-key", "CURSOR_API_KEY": "crsr_test"})
    text = path.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "PROXY_API_KEY=new-key" in text
    assert "SESSION_SECRET=stay" in text
    assert "CURSOR_API_KEY=crsr_test" in text
    assert text.count("PROXY_API_KEY=") == 1


def test_apply_secret_updates_overwrites_env_without_restart(hermes_root, monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "stale-key")
    get_settings(reload=True)
    apply_secret_updates({"CURSOR_API_KEY": "fresh-cursor-key"})
    settings = get_settings()
    assert settings.cursor_token() == "fresh-cursor-key"
    assert settings.secret("CURSOR_API_KEY") == "fresh-cursor-key"
    text = (hermes_root / "config" / "secrets.env").read_text(encoding="utf-8")
    assert "CURSOR_API_KEY=fresh-cursor-key" in text
    assert "PROXY_API_KEY=test-proxy-key" in text


def test_hermes_connect_returns_copy_fields(hermes_root):
    settings = get_settings(reload=True)
    data = hermes_connect(settings)
    assert data["choice"] == "30"
    values = {item["id"]: item["value"] for item in data["fields"]}
    assert values["base_url"].endswith("/v1")
    assert values["api_key"] == "test-proxy-key"
    assert values["model"] == "default"
    assert values["api_mode"] == "chat_completions"
    assert "30" in data["howto"]


def test_secrets_api_reload_and_put(hermes_root, monkeypatch):
    monkeypatch.setattr("app.adapters.qoder.account.public_qoder_status", lambda refresh=False: {"ok": False})
    monkeypatch.setattr("app.adapters.cursor.account.public_cursor_status", lambda refresh=False: {"ok": False})
    client = _client(hermes_root)
    _login(client)
    connect = client.get("/api/hermes-connect")
    assert connect.status_code == 200
    body = connect.json()
    assert body["fields"][0]["id"] == "choice"
    keys = {item["id"]: item["value"] for item in body["fields"]}
    assert keys["api_key"] == "test-proxy-key"
    assert "test-proxy-key" not in body["snippet"]

    saved = client.put("/api/secrets", json={"cursor_api_key": "cursor-from-ui", "qoder_token": "qoder-from-ui"})
    assert saved.status_code == 200
    hints = saved.json()
    assert hints["cursor_key_hint"].endswith("m-ui")
    assert hints["qoder_key_hint"].endswith("m-ui")
    assert "cursor-from-ui" not in str(hints)

    again = client.get("/api/settings").json()
    assert again["cursor_key_hint"].endswith("m-ui")
    assert again["qoder_key_hint"].endswith("m-ui")

    (hermes_root / "config" / "secrets.env").write_text(
        "PROXY_API_KEY=test-proxy-key\nSESSION_SECRET=test-session\nSETTINGS_PASSWORD=admin\nCURSOR_API_KEY=file-reloaded\n",
        encoding="utf-8",
    )
    reloaded = client.post("/api/secrets/reload")
    assert reloaded.status_code == 200
    assert reloaded.json()["cursor_key_hint"].endswith("aded")
