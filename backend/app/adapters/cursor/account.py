from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.engine.errors import is_network_error, is_quota_error

log = logging.getLogger("app.adapters.cursor.account")

BEIJING = timezone(timedelta(hours=8))
CACHE_TTL = 90.0
FETCH_TIMEOUT = 20.0
AUTH_STORE = Path.home() / ".cursor" / "sdk" / "auth.json"

_AUTH_LABEL = {
    "api_key": "个人 API Key",
    "sdk_store": "本机 SDK 登录",
    "missing": "未登录",
}

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {
    "at": 0.0,
    "loading": False,
    "load_started": 0.0,
    "usage": None,
    "error": None,
    "exceeded": False,
    "auth_invalid": False,
}

QUOTA_HINT = "Cursor 额度已用完，请给当前账号充值或更换 API Key 后再试。"
LOGIN_HELP = (
    "请先登录 Cursor：在设置页加载 CURSOR_API_KEY，"
    "或在本机完成 Cursor SDK 登录（~/.cursor/sdk/auth.json）。"
)
AUTH_HINT = "Cursor 登录已失效，请重新登录或更换 API Key 后再试。"
NETWORK_HINT = "Cursor 连不上云端（网络请求失败）。请检查本机网络后重试。"


def login_help_text(reason: str | None = None) -> str:
    if reason == "quota_exceeded":
        return QUOTA_HINT
    if reason == "auth_invalid":
        return AUTH_HINT
    return LOGIN_HELP


def friendly_cursor_error(text: str) -> str:
    raw = (text or "").strip() or "Cursor 执行失败"
    if is_quota_error(raw) or _is_rate_limit(raw):
        mark_quota_exceeded(raw)
        return QUOTA_HINT
    if _is_auth_error(raw):
        mark_auth_invalid(raw)
        return AUTH_HINT
    if is_network_error(raw):
        return NETWORK_HINT
    return raw


def _is_rate_limit(text: str) -> bool:
    body = (text or "").lower()
    return any(
        mark in body
        for mark in (
            "rate limit",
            "usage limit",
            "resource_exhausted",
            "usage_limit_exceeded",
            "rate_limit_exceeded",
        )
    )


def _is_auth_error(text: str) -> bool:
    body = (text or "").lower()
    return any(
        mark in body
        for mark in (
            "authenticationerror",
            "unauthenticated",
            "unauthorized",
            "api_key_not_found",
            "invalid api key",
            "not authenticated",
            "登录已失效",
            "api key",
        )
    ) and any(
        mark in body
        for mark in (
            "auth",
            "unauthor",
            "unauthenticated",
            "api_key",
            "api key",
            "登录",
            "401",
        )
    )


def reset_usage_cache() -> None:
    with _LOCK:
        _CACHE.update(
            {
                "at": 0.0,
                "loading": False,
                "load_started": 0.0,
                "usage": None,
                "error": None,
                "exceeded": False,
                "auth_invalid": False,
            }
        )


def mark_quota_exceeded(reason: str = "") -> None:
    with _LOCK:
        _CACHE["exceeded"] = True
        if reason:
            _CACHE["error"] = reason[:200]


def mark_auth_invalid(reason: str = "") -> None:
    with _LOCK:
        _CACHE["auth_invalid"] = True
        if reason:
            _CACHE["error"] = reason[:200]


def quota_exceeded() -> bool:
    with _LOCK:
        usage = _CACHE.get("usage") or {}
        quota = usage.get("quota")
        if isinstance(quota, dict) and "exceeded" in quota:
            return bool(quota.get("exceeded"))
        return bool(_CACHE["exceeded"])


def auth_invalid() -> bool:
    with _LOCK:
        return bool(_CACHE.get("auth_invalid"))


def fallback_reason(info: dict[str, Any] | None = None) -> str | None:
    from app.adapters.cursor.runner import describe_cursor

    data = info if info is not None else describe_cursor()
    if not data.get("installed"):
        return "sdk_missing"
    if auth_invalid():
        return "auth_invalid"
    if not data.get("ok"):
        return "not_logged_in"
    if quota_exceeded():
        return "quota_exceeded"
    return None


def public_cursor_status(refresh: bool = False) -> dict[str, Any]:
    from app.adapters.cursor.runner import describe_cursor

    info = describe_cursor()
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
        sticky_invalid = bool(_CACHE.get("auth_invalid"))
    if sticky_invalid and reason is None:
        reason = "auth_invalid"
    auth = str(info.get("auth") or "missing")
    account = usage.get("account") or _account_from_auth(auth, reason, info)
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
    logged_in = bool(info.get("ok") and reason != "auth_invalid")
    if reason == "quota_exceeded" or exceeded:
        shown = "额度已用完"
    elif reason == "auth_invalid":
        shown = "登录已失效"
    elif logged_in:
        shown = _AUTH_LABEL.get(auth, auth)
    else:
        shown = "未登录"
    return {
        "ok": logged_in,
        "engine": "cursor",
        "installed": bool(info.get("installed")),
        "cli_present": bool(info.get("cli_present")),
        "sdk_version": info.get("sdk_version") or "",
        "auth": auth,
        "auth_label": shown,
        "fallback_reason": reason,
        "account": account,
        "quota": quota,
        "expires_at": usage.get("expires_at") or info.get("expires_at") or "",
        "hint": login_help_text(reason) if reason else "已连接 Cursor。",
        "login_help": LOGIN_HELP,
        "loading": loading,
        "error": None if exceeded or reason == "auth_invalid" else fetch_error,
    }


def _account_from_auth(auth: str, reason: str | None, info: dict[str, Any]) -> dict[str, str]:
    profile = info.get("profile") if isinstance(info.get("profile"), dict) else {}
    label = str(profile.get("label") or profile.get("email") or "")
    if reason == "sdk_missing":
        return {"id": "", "type": "local", "label": "未安装 cursor-sdk"}
    if reason == "auth_invalid":
        return {"id": "", "type": auth or "missing", "label": label or "登录已失效"}
    if auth == "api_key":
        return {"id": "", "type": "api_key", "label": label or "个人 API Key"}
    if auth == "sdk_store":
        return {"id": "", "type": "sdk_store", "label": label or "本机 SDK 登录账号"}
    return {"id": "", "type": "local", "label": "尚未登录 Cursor"}


def _ensure_usage(refresh: bool = False) -> None:
    started = False
    with _LOCK:
        age = time.time() - float(_CACHE.get("at") or 0)
        loading = bool(_CACHE.get("loading"))
        started_at = float(_CACHE.get("load_started") or 0)
        if loading and started_at and time.time() - started_at > FETCH_TIMEOUT + 20:
            _CACHE["loading"] = False
            _CACHE["error"] = "读取额度超时"
            loading = False
        if loading:
            pass
        elif refresh or _CACHE.get("usage") is None or age >= CACHE_TTL:
            _CACHE["loading"] = True
            _CACHE["load_started"] = time.time()
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
        usage = _fetch_usage()
        with _LOCK:
            _CACHE["usage"] = usage
            _CACHE["at"] = time.time()
            _CACHE["error"] = None
            _CACHE["auth_invalid"] = False
            _CACHE["exceeded"] = bool((usage.get("quota") or {}).get("exceeded"))
    except Exception as exc:
        message = str(exc)
        invalid = _is_auth_error(message) or type(exc).__name__ == "AuthenticationError"
        log.warning("读取 Cursor 账号/额度失败：%s", exc)
        with _LOCK:
            _CACHE["error"] = message[:200]
            _CACHE["at"] = time.time()
            if invalid:
                _CACHE["auth_invalid"] = True
    finally:
        with _LOCK:
            _CACHE["loading"] = False


def _fetch_usage() -> dict[str, Any]:
    from app.adapters.cursor.runner import cursor_api_key

    key = cursor_api_key()
    session = _ide_session_token()
    if not key and not session:
        raise RuntimeError("未登录")
    summary = _fetch_usage_summary(key, session)
    if not summary:
        raise RuntimeError("已登录，但暂时读不到额度")
    store = read_sdk_store() or {}
    return normalize_usage({"email": store.get("email") or "", "name": ""}, summary)


def _fetch_usage_summary(api_key: str, session: str = "") -> dict[str, Any] | None:
    try:
        import httpx
    except Exception:
        return None
    urls = (
        "https://www.cursor.com/api/usage-summary",
        "https://cursor.com/api/usage-summary",
        "https://www.cursor.com/api/usage",
    )
    header_sets = _usage_header_sets(api_key, session)
    jobs = [(url, headers) for headers in header_sets for url in urls]
    if not jobs:
        return None

    def _one(url: str, headers: dict[str, str]) -> dict[str, Any] | None:
        try:
            with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
            if resp.status_code >= 400:
                log.info("Cursor 额度接口 %s → %s", url, resp.status_code)
                return None
            data = resp.json()
            if isinstance(data, dict) and _looks_like_usage(data):
                return data
        except Exception as exc:
            log.info("读取 Cursor 额度接口失败：%s", exc)
        return None

    with ThreadPoolExecutor(max_workers=min(6, len(jobs))) as pool:
        futures = [pool.submit(_one, url, headers) for url, headers in jobs]
        try:
            for future in as_completed(futures, timeout=12):
                data = future.result()
                if data:
                    return data
        except Exception:
            return None
    return None


def _usage_header_sets(api_key: str, session: str = "") -> list[dict[str, str]]:
    accept = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) hermes-agent-provider",
    }
    sets: list[dict[str, str]] = []
    for cookie in _cookie_variants(session):
        sets.append({**accept, "Cookie": cookie})
    if api_key:
        sets.append({**accept, "Authorization": f"Bearer {api_key}"})
    return sets


def _cookie_variants(session: str) -> list[str]:
    token = (session or "").strip()
    if not token:
        return []
    values = [token]
    if "::" in token:
        values.append(token.replace("::", "%3A%3A", 1))
    elif "%3A%3A" in token:
        values.append(token.replace("%3A%3A", "::", 1))
    else:
        sub = _jwt_sub(token)
        if sub:
            values.append(f"{sub}::{token}")
            values.append(f"{sub}%3A%3A{token}")
    cookies: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = f"WorkosCursorSessionToken={value}"
        if item not in seen:
            seen.add(item)
            cookies.append(item)
    return cookies


def _looks_like_usage(data: dict[str, Any]) -> bool:
    if any(
        key in data
        for key in (
            "individualUsage",
            "membershipType",
            "billingCycleEnd",
            "autoModelSelectedDisplayMessage",
            "autoPercentUsed",
            "apiPercentUsed",
        )
    ):
        return True
    plan = data.get("plan")
    return isinstance(plan, dict) and (
        "autoPercentUsed" in plan or "apiPercentUsed" in plan or "used" in plan
    )


def _ide_session_token() -> str:
    return _ide_vscdb_token() or _ide_storage_json_token()


def _ide_vscdb_token() -> str:
    appdata = os.environ.get("APPDATA") or ""
    db = Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    if not db.is_file():
        return ""
    try:
        import sqlite3

        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE '%cursorAuth%' "
                "OR key LIKE '%Workos%' OR key LIKE '%workos%' OR key LIKE '%SessionToken%'"
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        log.info("读取本机 Cursor 登录态失败：%s", exc)
        return ""
    session = ""
    access = ""
    user_id = ""
    for key, value in rows:
        text = value.decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else str(value or "")
        key_l = str(key).lower()
        if "userid" in key_l:
            cleaned = text.strip().strip('"')
            if cleaned and len(cleaned) < 80:
                user_id = cleaned
        token = _extract_session_token(text)
        if not token:
            continue
        if "workos" in key_l or "session" in key_l:
            session = token
        elif "accesstoken" in key_l or "access_token" in key_l:
            access = token
        elif not session and not access:
            session = token
    picked = session or access
    if picked and user_id and "::" not in picked and "%3A%3A" not in picked:
        picked = f"{user_id}::{picked}"
    return picked


def _ide_storage_json_token() -> str:
    appdata = os.environ.get("APPDATA") or ""
    path = Path(appdata) / "Cursor" / "User" / "globalStorage" / "storage.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    for key, value in data.items():
        key_l = str(key).lower()
        if "cursorauth" not in key_l and "workos" not in key_l:
            continue
        raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        token = _extract_session_token(raw)
        if token:
            return token
    return ""


def _extract_session_token(raw: str) -> str:
    text = (raw or "").strip().strip('"')
    if not text:
        return ""
    if text.startswith("{") or text.startswith("["):
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            for key in (
                "cachedWorkosSessionToken",
                "WorkosCursorSessionToken",
                "accessToken",
                "sessionToken",
                "token",
            ):
                value = loaded.get(key)
                if isinstance(value, str) and _looks_like_session_token(value):
                    return value.strip().strip('"')
        if isinstance(loaded, str) and _looks_like_session_token(loaded):
            return loaded.strip().strip('"')
    if _looks_like_session_token(text):
        return text
    return ""


def _looks_like_session_token(text: str) -> bool:
    value = (text or "").strip().strip('"')
    if len(value) < 20:
        return False
    if "::" in value or "%3A%3A" in value:
        return True
    if value.startswith("eyJ") and value.count(".") >= 2:
        return True
    return False


def _jwt_sub(token: str) -> str:
    parts = (token or "").split(".")
    if len(parts) < 2:
        return ""
    try:
        import base64

        padded = parts[1] + ("=" * (-len(parts[1]) % 4))
        data = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("sub") or data.get("id") or "").strip()


def normalize_usage(me: dict[str, Any] | None, summary: dict[str, Any] | None) -> dict[str, Any]:
    src = me or {}
    email = str(src.get("email") or "").strip()
    name = str(src.get("name") or "").strip()
    raw = summary or {}
    membership = str(raw.get("membershipType") or "").strip()
    account = {
        "id": email,
        "type": membership or "cursor",
        "label": name or email or (f"{membership} 账号" if membership else str(src.get("api_key_name") or "已登录账号")),
    }
    plan_raw = _plan_bucket(raw)
    auto_pct = _num((plan_raw or {}).get("autoPercentUsed")) if plan_raw else None
    api_pct = _num((plan_raw or {}).get("apiPercentUsed")) if plan_raw else None
    if auto_pct is not None or api_pct is not None:
        plan = _percent_view(auto_pct, note="含 Cursor Grok 和 Composer。超出后会消耗其他模型额度或按需计费。")
        other = _percent_view(api_pct, note="超出后按需计费。")
    else:
        plan = _quota_view(plan_raw)
        other = None
    on_demand = _quota_view(_on_demand_bucket(raw, "individualUsage"))
    shared = _quota_view(_on_demand_bucket(raw, "teamUsage"))
    unlimited = bool(raw.get("isUnlimited"))
    pools = [item for item in (plan, other) if item]
    extras = [item for item in (on_demand, shared) if item]
    if unlimited:
        exceeded = False
    elif pools:
        exceeded = all(item.get("exceeded") for item in pools) and not any(_has_credit(item) for item in extras)
    else:
        buckets = extras
        exceeded = bool(buckets) and not any(_has_credit(item) for item in buckets)
    primary = plan or other or on_demand or shared
    quota: dict[str, Any] | None = None
    if primary or exceeded or unlimited:
        quota = {
            **(primary or {"exceeded": False, "text": "不限量" if unlimited else "额度未知"}),
            "exceeded": exceeded,
            "text": "不限量" if unlimited else _combined_quota_text(plan, other, on_demand, shared, exceeded),
            "lines": _quota_lines(plan, other, on_demand, shared),
            "plan": plan,
            "other": other,
            "add_on": on_demand,
            "shared": shared,
        }
    return {
        "account": account,
        "quota": quota,
        "expires_at": _format_expires(raw.get("billingCycleEnd") or src.get("created_at")),
    }


def _plan_bucket(raw: dict[str, Any]) -> dict[str, Any] | None:
    individual = raw.get("individualUsage") if isinstance(raw.get("individualUsage"), dict) else {}
    plan = individual.get("plan") if isinstance(individual.get("plan"), dict) else raw.get("plan")
    return plan if isinstance(plan, dict) else None


def _on_demand_bucket(raw: dict[str, Any], key: str) -> dict[str, Any] | None:
    block = raw.get(key) if isinstance(raw.get(key), dict) else {}
    item = block.get("onDemand") if isinstance(block.get("onDemand"), dict) else None
    if not isinstance(item, dict):
        return None
    if item.get("enabled") is False and item.get("used") in (None, 0, "0"):
        return None
    return item


def _percent_view(percentage: float | None, *, note: str = "") -> dict[str, Any] | None:
    if percentage is None:
        return None
    pct = min(100.0, max(0.0, float(percentage)))
    remaining = max(0.0, 100.0 - pct)
    view = {
        "used": pct,
        "total": 100.0,
        "remaining": remaining,
        "percentage": pct,
        "unit": "%",
        "exceeded": pct >= 100,
        "text": f"已用 {int(round(pct))}%",
    }
    if note:
        view["note"] = note
    return view


def _quota_view(bucket: dict[str, Any] | None) -> dict[str, Any] | None:
    if not bucket:
        return None
    used = _num(bucket.get("used"))
    total = _num(bucket.get("limit") if bucket.get("limit") is not None else bucket.get("total"))
    remaining = _num(bucket.get("remaining"))
    percentage = _num(bucket.get("totalPercentUsed") or bucket.get("percentage"))
    exceeded = False
    if remaining is not None and remaining <= 0:
        exceeded = True
    elif remaining is None and total is not None and used is not None and used >= total:
        exceeded = True
    if remaining is None and used is not None and total is not None:
        remaining = max(total - used, 0)
    if percentage is None and used is not None and total:
        percentage = min(100.0, max(0.0, used / total * 100))
    return {
        "used": used,
        "total": total,
        "remaining": remaining,
        "percentage": percentage,
        "unit": "额度",
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


def _quota_lines(plan, other, on_demand, shared) -> list[str]:
    lines: list[str] = []
    if plan:
        label = "Cursor 模型" if plan.get("unit") == "%" else "套餐内"
        lines.append(f"{label} {_quota_line_body(plan)}")
    if other:
        lines.append(f"其他模型 {_quota_line_body(other)}")
    if on_demand:
        lines.append(f"按需 {_quota_line_body(on_demand)}")
    if shared:
        lines.append(f"团队 {_quota_line_body(shared)}")
    return lines


def _combined_quota_text(plan, other, on_demand, shared, exceeded: bool) -> str:
    lines = _quota_lines(plan, other, on_demand, shared)
    return " · ".join(lines) if lines else ("额度已用完" if exceeded else "额度未知")


def _quota_line_body(view: dict[str, Any]) -> str:
    if view.get("unit") == "%":
        pct = view.get("percentage")
        if view.get("exceeded"):
            return "已用完"
        return f"已用 {_fmt(float(pct))}%" if pct is not None else "额度未知"
    used, total, remaining = view.get("used"), view.get("total"), view.get("remaining")
    if view.get("exceeded") or (remaining is not None and remaining <= 0):
        if used is not None and total is not None:
            return f"已用完 {_fmt(float(used))} / {_fmt(float(total))}"
        return "已用完"
    if remaining is not None and total is not None:
        return f"剩余 {_fmt(float(remaining))} / {_fmt(float(total))}"
    if used is not None and total is not None:
        return f"已用 {_fmt(float(used))} / {_fmt(float(total))}"
    if remaining is not None:
        return f"剩余 {_fmt(float(remaining))}"
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


def _format_expires(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 1e12:
            stamp = stamp / 1000
        try:
            moment = datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone(BEIJING)
        except (OverflowError, OSError, ValueError):
            return ""
        return moment.strftime("%Y-%m-%d %H:%M")
    text = str(value).strip()
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(BEIJING)
    except ValueError:
        return text[:16]
    return moment.strftime("%Y-%m-%d %H:%M")


def read_sdk_store() -> dict[str, Any] | None:
    if not AUTH_STORE.is_file():
        return None
    try:
        data = json.loads(AUTH_STORE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    key = str(data.get("apiKey") or data.get("api_key") or "").strip()
    email = str(data.get("email") or "").strip()
    expires = data.get("apiKeyExpiresAtMs") or data.get("expiresAt")
    if not key and not email:
        return None
    return {"api_key": key, "email": email, "expires_at": _format_expires(expires)}
