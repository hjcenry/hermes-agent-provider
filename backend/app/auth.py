from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from app.config import Settings


def find_user(settings: Settings, username: str, password: str) -> dict[str, str] | None:
    for item in (settings.raw.get("auth") or {}).get("users") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("username") or "") != username:
            continue
        expected = str(item.get("password") or settings.settings_password() or "")
        if not expected or expected != password:
            return None
        return {
            "username": username,
            "role": str(item.get("role") or "admin"),
            "display_name": str(item.get("display_name") or username),
        }
    return None


def current_user(request: Request) -> dict[str, str]:
    user = request.session.get("user")
    if not isinstance(user, dict) or not user.get("username"):
        raise HTTPException(status_code=401, detail="请先登录")
    return {
        "username": str(user["username"]),
        "role": str(user.get("role") or "admin"),
        "display_name": str(user.get("display_name") or user["username"]),
    }


def login_user(request: Request, user: dict[str, Any]) -> None:
    request.session["user"] = user


def logout_user(request: Request) -> None:
    request.session.clear()
