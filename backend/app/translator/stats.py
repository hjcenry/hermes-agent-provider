from __future__ import annotations

import threading
from typing import Any

from app.translator.parse import ParseResult

_LOCK = threading.Lock()
_COUNTS = {"fence_ok": 0, "text": 0, "degraded": 0}
_LAST: dict[str, Any] | None = None
_LABELS = {
    "tool_calls": "成功围栏",
    "text": "纯文本",
    "degraded": "降级文本",
}


def reset_parse_stats() -> None:
    global _LAST
    with _LOCK:
        _COUNTS["fence_ok"] = 0
        _COUNTS["text"] = 0
        _COUNTS["degraded"] = 0
        _LAST = None


def record_parse(parsed: ParseResult) -> None:
    global _LAST
    if parsed.degraded:
        kind = "degraded"
        bucket = "degraded"
    elif parsed.kind == "tool_calls":
        kind = "tool_calls"
        bucket = "fence_ok"
    else:
        kind = "text"
        bucket = "text"
    tools = [str(item.get("name") or "") for item in parsed.calls if item.get("name")]
    preview = (parsed.text or "").replace("\n", " ").strip()
    if not preview and tools:
        preview = ",".join(tools)
    if len(preview) > 160:
        preview = preview[:160]
    with _LOCK:
        _COUNTS[bucket] += 1
        _LAST = {"kind": kind, "label": _LABELS[kind], "tools": tools, "preview": preview}


def public_parse_stats() -> dict[str, Any]:
    with _LOCK:
        last = (
            dict(_LAST)
            if _LAST
            else {"kind": "", "label": "", "tools": [], "preview": ""}
        )
        return {"ok": True, "last": last, "counts": dict(_COUNTS)}
