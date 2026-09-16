from __future__ import annotations

_QUOTA_MARKERS = (
    "quota exceeded",
    "insufficient_quota",
    "isquotaexceeded",
    "credits exhausted",
    "额度已用完",
    "额度用完",
    "配额不足",
    "配额已用完",
    "用量已尽",
    "余额不足",
    "token 用完",
    "token用完",
    "rate limit",
    "usage limit",
    "resource_exhausted",
    "usage_limit_exceeded",
    "rate_limit_exceeded",
)

_NETWORK_MARKERS = (
    "network request failed",
    "err_network",
    "econnreset",
    "econnrefused",
    "enotfound",
    "socket hang up",
    "fetch failed",
    "connection reset",
    "temporarily unavailable",
)

_LOGIN_MARKERS = (
    "not authenticated",
    "unauthenticated",
    "unauthorized",
    "authenticationerror",
    "invalid api key",
    "api_key_not_found",
    "登录已失效",
    "未登录",
)


def is_quota_error(text: str) -> bool:
    body = (text or "").lower()
    return any(mark.lower() in body for mark in _QUOTA_MARKERS)


def is_network_error(text: str) -> bool:
    body = (text or "").lower()
    return any(mark in body for mark in _NETWORK_MARKERS)


def classify_engine_error(text: str) -> str:
    body = (text or "").lower()
    if is_quota_error(body):
        return "quota"
    if any(mark in body for mark in _LOGIN_MARKERS):
        return "login"
    if "timeout" in body or "超时" in (text or ""):
        return "timeout"
    return "engine"
