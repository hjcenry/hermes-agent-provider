from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI

from app.config import Settings, _read_yaml, deep_merge, get_settings

SECRET_ENV_KEYS = {
    "proxy_api_key": "PROXY_API_KEY",
    "cursor_api_key": "CURSOR_API_KEY",
    "qoder_token": "QODER_PERSONAL_ACCESS_TOKEN",
}


def save_local_overlay(overlay: dict[str, Any]) -> Settings:
    settings = get_settings()
    path = settings.root / "config" / "local.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = deep_merge(_read_yaml(path), overlay)
    path.write_text(
        yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return get_settings(reload=True)


def apply_settings(app: FastAPI, settings: Settings | None = None) -> Settings:
    cfg = settings or get_settings(reload=True)
    app.state.settings = cfg
    return cfg


def upsert_secrets(path: Path, updates: dict[str, str]) -> None:
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = raw.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    pending = [key for key in updates if key not in seen]
    if pending and out and out[-1] != "":
        out.append("")
    for key in pending:
        out.append(f"{key}={updates[key]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")


def reset_engine_caches() -> None:
    from app.adapters.cursor import account as cursor_account
    from app.adapters.cursor import runner as cursor_runner
    from app.adapters.qoder import account as qoder_account
    from app.adapters.qoder import runner as qoder_runner

    cursor_account.reset_usage_cache()
    qoder_account.reset_usage_cache()
    qoder_runner.reset_cli_profile()
    qoder_runner.reset_qoder_pool()
    cursor_runner.reset_cursor_pool()


def apply_secret_updates(updates: dict[str, str], app: FastAPI | None = None) -> Settings:
    settings = get_settings()
    path = settings.root / "config" / "secrets.env"
    if updates:
        upsert_secrets(path, updates)
    cfg = get_settings(reload=True, overwrite_env=True)
    reset_engine_caches()
    if app is not None:
        app.state.settings = cfg
    return cfg


def secret_hints(settings: Settings) -> dict[str, str]:
    return {
        "proxy_key_hint": settings.proxy_key_hint(),
        "cursor_key_hint": settings.key_hint("CURSOR_API_KEY"),
        "qoder_key_hint": settings.key_hint("QODER_PERSONAL_ACCESS_TOKEN")
        or settings.key_hint("QODERCN_PERSONAL_ACCESS_TOKEN"),
    }


def hermes_snippet(settings: Settings) -> str:
    return (
        "model:\n"
        "  default: default\n"
        "  provider: custom\n"
        f"  base_url: {settings.public_base_url()}\n"
        "  api_key: YOUR_PROXY_API_KEY\n"
        "  api_mode: chat_completions\n"
        "  discover_models: true\n"
    )


def hermes_connect(settings: Settings) -> dict[str, Any]:
    base_url = settings.public_base_url()
    api_key = settings.proxy_api_key()
    fields = [
        {"id": "choice", "label": "hermes model 选项", "value": "30", "hint": "Custom endpoint（手动输入 URL）"},
        {"id": "base_url", "label": "API base URL", "value": base_url},
        {"id": "api_key", "label": "API key", "value": api_key, "secret": True},
        {"id": "model", "label": "Model name", "value": "default", "hint": "也可用设置页里的完整 id，例如 cursor/grok-4.6"},
        {"id": "api_mode", "label": "API mode", "value": "chat_completions"},
    ]
    return {
        "choice": "30",
        "choice_label": "30. Custom endpoint (enter URL manually)",
        "also_ok": "29 和 30 都会问 URL / Key；请选 30，这是官方的手动填地址向导。",
        "howto": (
            "在终端执行 hermes model → 选 30 → 依次粘贴 API base URL 和 API key。"
            "探测模型时选 default（或 chat_completions 模式下的完整 id）。"
        ),
        "fields": fields,
        "snippet": hermes_snippet(settings),
    }
