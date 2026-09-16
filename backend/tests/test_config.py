from pathlib import Path

from app.config import deep_merge, get_settings, load_settings

ROOT_ENV = "HERMES_AGENT_PROVIDER_ROOT"


def _write_config(root: Path, default: str, local: str = "", secrets: str = "") -> None:
    cfg = root / "config"
    cfg.mkdir()
    cfg.joinpath("default.yaml").write_text(default, encoding="utf-8")
    if local:
        cfg.joinpath("local.yaml").write_text(local, encoding="utf-8")
    if secrets:
        cfg.joinpath("secrets.env").write_text(secrets, encoding="utf-8")


def test_deep_merge_keeps_nested_default_and_overrides_engine():
    base = {
        "engines": {
            "default": "qoder",
            "models": {"qoder": "qmodel_38max", "cursor": "grok-4.6"},
        }
    }
    overlay = {"engines": {"default": "cursor", "models": {"cursor": "composer-2.5"}}}
    merged = deep_merge(base, overlay)
    assert merged["engines"]["default"] == "cursor"
    assert merged["engines"]["models"]["cursor"] == "composer-2.5"
    assert merged["engines"]["models"]["qoder"] == "qmodel_38max"


def test_load_settings_merges_default_local_and_secrets(tmp_path: Path, monkeypatch):
    _write_config(
        tmp_path,
        default=(
            "server:\n  host: 127.0.0.1\n  port: 8765\n"
            "engines:\n  default: qoder\n  models:\n    qoder: qmodel_38max\n    cursor: grok-4.6\n"
            "paths:\n  workspace: data/workspace\n"
        ),
        local="server:\n  port: 8877\nengines:\n  default: cursor\n",
        secrets="PROXY_API_KEY=test-proxy-key\nSESSION_SECRET=test-session\n",
    )
    monkeypatch.setenv(ROOT_ENV, str(tmp_path))
    settings = load_settings()
    assert settings.server_host() == "127.0.0.1"
    assert settings.server_port() == 8877
    assert settings.default_engine() == "cursor"
    assert settings.default_engine_model("qoder") == "qmodel_38max"
    assert settings.default_engine_model("cursor") == "grok-4.6"
    assert settings.proxy_api_key() == "test-proxy-key"
    assert settings.session_secret() == "test-session"
    assert settings.workspace_path() == tmp_path / "data" / "workspace"


def test_get_settings_reload_picks_up_local_change(tmp_path: Path, monkeypatch):
    _write_config(
        tmp_path,
        default="engines:\n  default: qoder\n",
        local="engines:\n  default: qoder\n",
        secrets="PROXY_API_KEY=k1\n",
    )
    monkeypatch.setenv(ROOT_ENV, str(tmp_path))
    first = get_settings(reload=True)
    assert first.default_engine() == "qoder"
    (tmp_path / "config" / "local.yaml").write_text("engines:\n  default: cursor\n", encoding="utf-8")
    second = get_settings(reload=True)
    assert second.default_engine() == "cursor"
