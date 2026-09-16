from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.adapters.cursor import account as cursor_account
from app.adapters.qoder import account as qoder_account
from app.auth import current_user, find_user, login_user, logout_user
from app.config import Settings
from app.models import list_engine_models
from app.settings_io import (
    SECRET_ENV_KEYS,
    apply_secret_updates,
    apply_settings,
    hermes_connect,
    hermes_snippet,
    save_local_overlay,
    secret_hints,
)

router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str


class ActiveBody(BaseModel):
    engine: str


class SettingsBody(BaseModel):
    engine: str | None = None
    models: dict[str, str] | None = None
    workspace: str | None = None
    timeout_sec: int | None = None
    max_concurrency: int | None = None
    max_turns: int | None = None


class SecretsBody(BaseModel):
    cursor_api_key: str | None = None
    qoder_token: str | None = None
    proxy_api_key: str | None = None


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/api/login")
def login(body: LoginBody, request: Request) -> dict[str, Any]:
    user = find_user(_settings(request), body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码不对")
    login_user(request, user)
    return {"ok": True, "user": user}


@router.post("/api/logout")
def logout(request: Request) -> dict[str, bool]:
    logout_user(request)
    return {"ok": True}


@router.get("/api/me")
def me(user: dict[str, str] = Depends(current_user)) -> dict[str, Any]:
    return {"user": user}


@router.get("/api/engines/status")
def engines_status(
    request: Request,
    _: dict[str, str] = Depends(current_user),
    refresh: bool = False,
) -> dict[str, Any]:
    settings = _settings(request)
    qoder = qoder_account.public_qoder_status(refresh=refresh)
    cursor = cursor_account.public_cursor_status(refresh=refresh)
    if qoder.get("ok"):
        from app.adapters.qoder.runner import warmup_qoder

        warmup_qoder(settings.workspace_path())
    if cursor.get("ok"):
        from app.adapters.cursor.runner import warmup_cursor

        warmup_cursor(settings.workspace_path())
    return {
        "ok": True,
        "active": settings.default_engine(),
        "defaults": {
            "engine": settings.default_engine(),
            "models": {
                "qoder": settings.default_engine_model("qoder"),
                "cursor": settings.default_engine_model("cursor"),
            },
        },
        "engines": [
            {"id": "qoder", "label": "Qoder"},
            {"id": "cursor", "label": "Cursor"},
        ],
        "qoder": qoder,
        "cursor": cursor,
    }


@router.put("/api/engines/active")
def set_active(
    body: ActiveBody,
    request: Request,
    _: dict[str, str] = Depends(current_user),
) -> dict[str, Any]:
    engine = (body.engine or "").strip().lower()
    if engine not in {"qoder", "cursor"}:
        raise HTTPException(status_code=400, detail="引擎只能是 qoder 或 cursor")
    settings = apply_settings(request.app, save_local_overlay({"engines": {"default": engine}}))
    return {"ok": True, "active": settings.default_engine()}


@router.get("/api/engines/models")
def engines_models(
    request: Request,
    _: dict[str, str] = Depends(current_user),
    engine: str = "",
) -> dict[str, Any]:
    settings = _settings(request)
    try:
        return list_engine_models(engine, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/settings")
def get_settings_view(
    request: Request,
    _: dict[str, str] = Depends(current_user),
) -> dict[str, Any]:
    settings = _settings(request)
    return {
        "engine": settings.default_engine(),
        "models": {
            "qoder": settings.default_engine_model("qoder"),
            "cursor": settings.default_engine_model("cursor"),
        },
        "workspace": settings.workspace_config(),
        "timeout_sec": settings.timeout_sec(),
        "max_concurrency": settings.max_concurrency(),
        "max_turns": settings.max_turns(),
        "listen": settings.listen_addr(),
        "base_url": settings.public_base_url(),
        "proxy_key_hint": settings.proxy_key_hint(),
        "cursor_key_hint": secret_hints(settings)["cursor_key_hint"],
        "qoder_key_hint": secret_hints(settings)["qoder_key_hint"],
        "restart_hint": "改端口或监听地址后须重启后端。引擎令牌可在本页加载，不必重启。",
    }


@router.put("/api/settings")
def put_settings(
    body: SettingsBody,
    request: Request,
    _: dict[str, str] = Depends(current_user),
) -> dict[str, Any]:
    overlay: dict[str, Any] = {}
    if body.engine is not None:
        engine = body.engine.strip().lower()
        if engine not in {"qoder", "cursor"}:
            raise HTTPException(status_code=400, detail="引擎只能是 qoder 或 cursor")
        overlay.setdefault("engines", {})["default"] = engine
    if body.models:
        models: dict[str, str] = {}
        for key in ("qoder", "cursor"):
            value = str(body.models.get(key) or "").strip()
            if value:
                models[key] = value
        if models:
            overlay.setdefault("engines", {})["models"] = models
    if body.workspace is not None:
        workspace = body.workspace.strip() or "data/workspace"
        overlay.setdefault("paths", {})["workspace"] = workspace
    runtime: dict[str, int] = {}
    if body.timeout_sec is not None:
        if body.timeout_sec < 1:
            raise HTTPException(status_code=400, detail="timeout_sec 必须大于 0")
        runtime["timeout_sec"] = body.timeout_sec
    if body.max_concurrency is not None:
        if body.max_concurrency < 1:
            raise HTTPException(status_code=400, detail="max_concurrency 必须大于 0")
        runtime["max_concurrency"] = body.max_concurrency
    if body.max_turns is not None:
        if body.max_turns < 1:
            raise HTTPException(status_code=400, detail="max_turns 必须大于 0")
        runtime["max_turns"] = body.max_turns
    if runtime:
        overlay["runtime"] = runtime
    settings = apply_settings(request.app, save_local_overlay(overlay))
    return {"ok": True, "engine": settings.default_engine()}


@router.get("/api/parse-stats")
def parse_stats(_: dict[str, str] = Depends(current_user)) -> dict[str, Any]:
    from app.translator.stats import public_parse_stats

    return public_parse_stats()


@router.get("/api/hermes-snippet")
def get_hermes_snippet(
    request: Request,
    _: dict[str, str] = Depends(current_user),
) -> dict[str, str]:
    return {"text": hermes_snippet(_settings(request))}


@router.get("/api/hermes-connect")
def get_hermes_connect(
    request: Request,
    _: dict[str, str] = Depends(current_user),
) -> dict[str, Any]:
    return hermes_connect(_settings(request))


def _secret_updates(body: SecretsBody) -> dict[str, str]:
    updates: dict[str, str] = {}
    mapping = {
        "cursor_api_key": body.cursor_api_key,
        "qoder_token": body.qoder_token,
        "proxy_api_key": body.proxy_api_key,
    }
    for field, value in mapping.items():
        text = (value or "").strip()
        if text:
            updates[SECRET_ENV_KEYS[field]] = text
    return updates


@router.put("/api/secrets")
def put_secrets(
    body: SecretsBody,
    request: Request,
    _: dict[str, str] = Depends(current_user),
) -> dict[str, Any]:
    updates = _secret_updates(body)
    if not updates:
        raise HTTPException(status_code=400, detail="没有要写入的令牌")
    settings = apply_secret_updates(updates, request.app)
    return {"ok": True, **secret_hints(settings)}


@router.post("/api/secrets/reload")
def reload_secrets(
    request: Request,
    _: dict[str, str] = Depends(current_user),
) -> dict[str, Any]:
    settings = apply_secret_updates({}, request.app)
    return {"ok": True, **secret_hints(settings)}

