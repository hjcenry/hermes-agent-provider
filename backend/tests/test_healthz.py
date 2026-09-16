from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app

ROOT_ENV = "HERMES_AGENT_PROVIDER_ROOT"


def _write_config(root: Path, *, secrets: str) -> None:
    cfg = root / "config"
    cfg.mkdir()
    cfg.joinpath("default.yaml").write_text(
        "server:\n  host: 127.0.0.1\n  port: 8765\n"
        "engines:\n  default: qoder\n  models:\n    qoder: qmodel_38max\n    cursor: grok-4.6\n",
        encoding="utf-8",
    )
    cfg.joinpath("secrets.env").write_text(secrets, encoding="utf-8")


def test_healthz_ok_without_auth(tmp_path: Path, monkeypatch):
    _write_config(tmp_path, secrets="PROXY_API_KEY=test-proxy-key\n")
    monkeypatch.setenv(ROOT_ENV, str(tmp_path))
    client = TestClient(create_app(load_settings()))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_create_app_requires_proxy_api_key(tmp_path: Path, monkeypatch):
    _write_config(tmp_path, secrets="SESSION_SECRET=only-session\n")
    monkeypatch.setenv(ROOT_ENV, str(tmp_path))
    monkeypatch.delenv("PROXY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PROXY_API_KEY"):
        create_app(load_settings())
