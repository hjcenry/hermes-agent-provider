from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

ROOT_ENV = "HERMES_AGENT_PROVIDER_ROOT"
_LEGACY_ROOT_ENVS = ("CURSOR_TO_OPENAI_ROOT", "ENGINE_RELAY_ROOT", "J2000_HERMES_ROOT")


def project_root() -> Path:
    raw = (os.environ.get(ROOT_ENV) or "").strip()
    if not raw:
        for key in _LEGACY_ROOT_ENVS:
            raw = (os.environ.get(key) or "").strip()
            if raw:
                break
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2]


def deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for key, value in overlay.items():
            if key in out:
                out[key] = deep_merge(out[key], value)
            else:
                out[key] = value
        return out
    return overlay


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必须是 YAML 对象")
    return data


def _read_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = dotenv_values(path)
    return {str(key): str(value) for key, value in values.items() if key and value is not None}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    root: Path
    raw: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)

    def server_host(self) -> str:
        return str((self.raw.get("server") or {}).get("host") or "127.0.0.1").strip() or "127.0.0.1"

    def server_port(self) -> int:
        return _int((self.raw.get("server") or {}).get("port"), 8765) or 8765

    @property
    def engines(self) -> dict[str, Any]:
        return dict(self.raw.get("engines") or {})

    @property
    def paths(self) -> dict[str, str]:
        return dict(self.raw.get("paths") or {})

    def default_engine(self) -> str:
        raw = str(self.engines.get("default") or "qoder").strip().lower()
        return raw if raw in {"qoder", "cursor"} else "qoder"

    def default_engine_model(self, engine: str) -> str:
        name = (engine or "").strip().lower()
        if name not in {"qoder", "cursor"}:
            name = self.default_engine()
        fallback = "grok-4.6" if name == "cursor" else "qmodel_38max"
        models = self.engines.get("models")
        if not isinstance(models, dict):
            return fallback
        value = str(models.get(name) or "").strip()
        return value or fallback

    def workspace_path(self) -> Path:
        raw = str(self.paths.get("workspace") or "data/workspace").strip() or "data/workspace"
        path = Path(raw)
        return path if path.is_absolute() else self.root / path

    def secret(self, key: str) -> str:
        return (self.secrets.get(key) or os.environ.get(key) or "").strip()

    def proxy_api_key(self) -> str:
        return self.secret("PROXY_API_KEY")

    def require_proxy_api_key(self) -> str:
        key = self.proxy_api_key()
        if not key:
            raise RuntimeError("未配置 PROXY_API_KEY，请写入 config/secrets.env")
        return key

    def session_secret(self) -> str:
        return self.secret("SESSION_SECRET") or "hermes-agent-provider-dev-secret"

    def settings_password(self) -> str:
        return self.secret("SETTINGS_PASSWORD")

    def cursor_token(self) -> str:
        return self.secret("CURSOR_API_KEY")

    def qoder_token(self) -> str:
        return self.secret("QODER_PERSONAL_ACCESS_TOKEN") or self.secret("QODERCN_PERSONAL_ACCESS_TOKEN")

    def key_hint(self, key: str) -> str:
        return mask_secret(self.secret(key))

    def timeout_sec(self) -> int:
        return _int((self.raw.get("runtime") or {}).get("timeout_sec"), 180) or 180

    def max_turns(self) -> int:
        return _int((self.raw.get("runtime") or {}).get("max_turns"), 2) or 2

    def max_concurrency(self) -> int:
        return _int((self.raw.get("runtime") or {}).get("max_concurrency"), 2) or 2

    def workspace_config(self) -> str:
        return str(self.paths.get("workspace") or "data/workspace").strip() or "data/workspace"

    def listen_addr(self) -> str:
        return f"{self.server_host()}:{self.server_port()}"

    def public_base_url(self) -> str:
        return f"http://{self.listen_addr()}/v1"

    def proxy_key_hint(self) -> str:
        return mask_secret(self.proxy_api_key())


def mask_secret(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    return "****" + text[-4:]


_CACHED: Settings | None = None


def apply_secret_env(secrets: dict[str, str], *, overwrite: bool = False) -> None:
    for key, value in secrets.items():
        if overwrite or key not in os.environ:
            os.environ[key] = value


def load_settings(*, overwrite_env: bool = False) -> Settings:
    root = project_root()
    cfg_dir = root / "config"
    raw = deep_merge(_read_yaml(cfg_dir / "default.yaml"), _read_yaml(cfg_dir / "local.yaml"))
    secrets = _read_secrets(cfg_dir / "secrets.env")
    apply_secret_env(secrets, overwrite=overwrite_env)
    return Settings(root=root, raw=raw, secrets=secrets)


def get_settings(reload: bool = False, *, overwrite_env: bool = False) -> Settings:
    global _CACHED
    if _CACHED is None or reload or overwrite_env or _CACHED.root != project_root():
        _CACHED = load_settings(overwrite_env=overwrite_env)
    return _CACHED
