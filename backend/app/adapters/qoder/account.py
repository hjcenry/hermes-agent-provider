from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.engine.errors import is_quota_error

log = logging.getLogger("app.adapters.qoder.account")

BEIJING = timezone(timedelta(hours=8))
CACHE_TTL = 90.0
CONNECT_TIMEOUT = 45.0
USAGE_TIMEOUT = 25.0
FETCH_TIMEOUT = CONNECT_TIMEOUT + USAGE_TIMEOUT

_AUTH_LABEL = {"pat": "个人令牌", "qodercli": "本机 qodercli", "missing": "未登录"}
_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"at": 0.0, "loading": False, "usage": None, "error": None, "exceeded": False}

LOGIN_HELP = (
    "请先登录 Qoder：本机执行 qodercli login，或在设置页加载个人令牌。"
)
QUOTA_HINT = "Qoder 额度已用完，请充值或更换 Token 后再试。"


def login_help_text(reason: str | None = None) -> str:
    return QUOTA_HINT if reason == "quota_exceeded" else LOGIN_HELP


def friendly_qoder_error(text: str) -> str:
    raw = (text or "").strip() or "Qoder 执行失败"
    if is_quota_error(raw):
        mark_quota_exceeded(raw)
        return QUOTA_HINT
    return raw


def reset_usage_cache() -> None:
    with _LOCK:
        _CACHE.update({"at": 0.0, "loading": False, "usage": None, "error": None, "exceeded": False})


def mark_quota_exceeded(reason: str = "") -> None:
    with _LOCK:
        _CACHE["exceeded"] = True
        if reason:
            _CACHE["error"] = reason[:200]


def quota_exceeded() -> bool:
    with _LOCK:
        usage = _CACHE.get("usage") or {}
        quota = usage.get("quota")
        if isinstance(quota, dict) and "exceeded" in quota:
            return bool(quota.get("exceeded"))
        return bool(_CACHE["exceeded"])


def fallback_reason(info: dict[str, Any] | None = None) -> str | None:
    from app.adapters.qoder.runner import describe_qoder

    data = info if info is not None else describe_qoder()
    if not data.get("installed"):
        return "sdk_missing"
    if not data.get("ok"):
        return "not_logged_in"
    if quota_exceeded():
        return "quota_exceeded"
    return None


def public_qoder_status(refresh: bool = False) -> dict[str, Any]:
    from app.adapters.qoder.runner import describe_qoder

    info = describe_qoder()
    reason = fallback_reason(info)
    if info.get("ok") and reason != "sdk_missing":
        _ensure_usage(refresh=refresh)
        if refresh:
            reason = fallback_reason(info)
    with _LOCK:
        usage = dict(_CACHE.get("usage") or {})
        loading = bool(_CACHE.get("loading"))
        fetch_error = _CACHE.get("error")
        sticky_exceeded = bool(_CACHE.get("exceeded"))
    quota = usage.get("quota")
    if isinstance(quota, dict):
        exceeded = bool(quota.get("exceeded"))
        quota = dict(quota)
    elif sticky_exceeded:
        exceeded = True
        quota = {"exceeded": True, "text": "额度已用完"}
    else:
        exceeded = False
        quota = None
    logged_in = bool(info.get("ok"))
    if reason == "quota_exceeded" or exceeded:
        shown = "额度已用完"
    elif logged_in:
        shown = _AUTH_LABEL.get(str(info.get("auth") or ""), str(info.get("auth") or ""))
    else:
        shown = "未登录"
    profile = info.get("profile") if isinstance(info.get("profile"), dict) else {}
    account = usage.get("account") or {"id": "", "type": str(info.get("auth") or ""), "label": shown}
    if isinstance(account, dict) and profile.get("label"):
        account = {
            **account,
            "label": str(profile.get("label") or account.get("label") or shown),
            "id": str(account.get("id") or profile.get("email") or ""),
        }
    return {
        "ok": logged_in,
        "engine": "qoder",
        "installed": bool(info.get("installed")),
        "cli_present": bool(info.get("cli_present")),
        "sdk_version": info.get("sdk_version") or "",
        "auth": info.get("auth") or "missing",
        "auth_label": shown,
        "fallback_reason": reason,
        "account": account,
        "quota": quota,
        "expires_at": usage.get("expires_at") or "",
        "hint": login_help_text(reason) if reason else "已连接 Qoder。",
        "login_help": LOGIN_HELP,
        "loading": loading,
        "error": None if exceeded else fetch_error,
    }


def _ensure_usage(refresh: bool = False) -> None:
    started = False
    with _LOCK:
        age = time.time() - float(_CACHE.get("at") or 0)
        if _CACHE.get("loading"):
            pass
        elif refresh or _CACHE.get("usage") is None or age >= CACHE_TTL:
            _CACHE["loading"] = True
            started = True
        else:
            return
    if started:
        thread = threading.Thread(target=_refresh_usage, daemon=True)
        thread.start()
        if refresh:
            thread.join(timeout=FETCH_TIMEOUT + 8)
    elif refresh:
        deadline = time.time() + FETCH_TIMEOUT + 8
        while time.time() < deadline:
            with _LOCK:
                if not _CACHE.get("loading"):
                    return
            time.sleep(0.15)


def _refresh_usage() -> None:
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        usage = asyncio.run(_fetch_usage())
        with _LOCK:
            _CACHE["usage"] = usage
            _CACHE["at"] = time.time()
            _CACHE["error"] = None
            _CACHE["exceeded"] = bool((usage.get("quota") or {}).get("exceeded"))
    except Exception as exc:
        log.warning("读取 Qoder 额度失败：%s", exc)
        with _LOCK:
            _CACHE["error"] = str(exc)[:200]
            _CACHE["at"] = time.time()
    finally:
        with _LOCK:
            _CACHE["loading"] = False


async def _fetch_usage() -> dict[str, Any]:
    from qoder_agent_sdk import QoderAgentOptions, QoderSDKClient

    from app.adapters.qoder.runner import qoder_auth
    from app.config import get_settings

    cwd = get_settings().workspace_path()
    cwd.mkdir(parents=True, exist_ok=True)
    client = QoderSDKClient(options=QoderAgentOptions(auth=qoder_auth(), cwd=str(cwd)))
    await asyncio.wait_for(client.connect(), timeout=CONNECT_TIMEOUT)
    try:
        raw = await asyncio.wait_for(client.get_usage_info(), timeout=USAGE_TIMEOUT)
    finally:
        await client.disconnect()
    return normalize_usage(raw)


def normalize_usage(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = raw or {}
    user_id = str(src.get("userId") or "").strip()
    user_type = str(src.get("userType") or "").strip()
    account = {
        "id": _public_account_id(user_id),
        "type": user_type,
        "label": _account_label(user_id, user_type),
    }
    plan = _quota_view(src.get("userQuota") if isinstance(src.get("userQuota"), dict) else None)
    add_on = _quota_view(src.get("addOnQuota") if isinstance(src.get("addOnQuota"), dict) else None)
    shared = _quota_view(src.get("orgResourcePackage") if isinstance(src.get("orgResourcePackage"), dict) else None)
    buckets = [item for item in (plan, add_on, shared) if item]
    usable = any(_has_credit(item) for item in buckets)
    exceeded = (not usable) if buckets else bool(src.get("isQuotaExceeded"))
    primary = plan or add_on or shared
    quota = None
    if primary or exceeded:
        quota = {
            **(primary or {"exceeded": True, "text": "额度已用完"}),
            "exceeded": exceeded,
            "text": _combined_quota_text(plan, add_on, shared, exceeded),
            "lines": _quota_lines(plan, add_on, shared),
            "plan": plan,
            "add_on": add_on,
            "shared": shared,
        }
    return {"account": account, "quota": quota, "expires_at": _format_expires(src.get("expiresAt"))}


def _quota_view(bucket: dict[str, Any] | None) -> dict[str, Any] | None:
    if not bucket:
        return None
    used = _num(bucket.get("used"))
    total = _num(bucket.get("total"))
    if total is None:
        total = _num(bucket.get("cap"))
    remaining = _num(bucket.get("remaining"))
    percentage = _num(bucket.get("percentage"))
    unit = str(bucket.get("unit") or "credits")
    exceeded = False
    if remaining is not None and remaining <= 0:
        exceeded = True
    elif remaining is None and percentage is not None and percentage >= 100:
        exceeded = True
    if remaining is None and used is not None and total is not None:
        remaining = max(total - used, 0)
    return {
        "used": used,
        "total": total,
        "remaining": remaining,
        "percentage": percentage,
        "unit": unit,
        "exceeded": exceeded,
        "text": "额度已用完" if exceeded else "额度可用",
    }


def _has_credit(view: dict[str, Any] | None) -> bool:
    if not view:
        return False
    remaining = view.get("remaining")
    if remaining is not None:
        return float(remaining) > 0
    return not view.get("exceeded")


def _quota_lines(plan, add_on, shared) -> list[str]:
    lines: list[str] = []
    if plan:
        lines.append(f"套餐内 {_quota_line_body(plan)}")
    if add_on:
        lines.append(f"加量包 {_quota_line_body(add_on)}")
    if shared:
        lines.append(f"资源包 {_quota_line_body(shared)}")
    return lines


def _combined_quota_text(plan, add_on, shared, exceeded: bool) -> str:
    lines = _quota_lines(plan, add_on, shared)
    return " · ".join(lines) if lines else ("额度已用完" if exceeded else "额度未知")


def _quota_line_body(view: dict[str, Any]) -> str:
    used, total, remaining = view.get("used"), view.get("total"), view.get("remaining")
    if view.get("exceeded") or (remaining is not None and remaining <= 0):
        if used is not None and total is not None:
            return f"已用完 {_fmt(float(used))} / {_fmt(float(total))}"
        return "已用完"
    if remaining is not None and total is not None:
        return f"剩余 {_fmt(float(remaining))} / {_fmt(float(total))}"
    if used is not None and total is not None:
        return f"已用 {_fmt(float(used))} / {_fmt(float(total))}"
    return str(view.get("text") or "额度未知")


def _fmt(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}"


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _account_label(user_id: str, user_type: str) -> str:
    return _public_account_id(user_id) or user_type or "已登录账号"


def _public_account_id(user_id: str) -> str:
    text = (user_id or "").strip()
    if not text:
        return ""
    if "@" in text or len(text) <= 24:
        return text
    return f"{text[:4]}…{text[-4:]}"


def _format_expires(value: Any) -> str:
    stamp = _num(value)
    if stamp is None:
        return ""
    if stamp > 1e12:
        stamp = stamp / 1000
    try:
        moment = datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone(BEIJING)
    except (OverflowError, OSError, ValueError):
        return ""
    return moment.strftime("%Y-%m-%d %H:%M")
