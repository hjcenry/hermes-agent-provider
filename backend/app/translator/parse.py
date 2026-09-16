from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

_FENCE = re.compile(r"```hermes-proxy\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


@dataclass
class ParseResult:
    kind: str
    text: str = ""
    calls: list[dict[str, str]] = field(default_factory=list)
    degraded: bool = False


def parse_output(
    raw: str,
    tool_names: list[str] | None = None,
    tool_choice: str = "auto",
) -> ParseResult:
    text = (raw or "").strip()
    names = [str(item) for item in (tool_names or []) if str(item)]
    choice = (tool_choice or "auto").strip() or "auto"
    if choice == "none":
        return ParseResult(kind="text", text=text)

    named = None if choice in {"auto", "required"} else choice
    fence = _FENCE.search(text)
    if fence:
        loaded = _load_json(fence.group(1))
        if loaded is None:
            return ParseResult(kind="text", text=text, degraded=True)
        parsed = _from_object(loaded, text)
        return _normalize(parsed, text, names, named)

    loaded = _load_json(text)
    if loaded is not None:
        parsed = _from_object(loaded, text)
        return _normalize(parsed, text, names, named)
    return ParseResult(kind="text", text=text)


def _load_json(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _from_object(data: dict[str, Any] | None, original: str) -> ParseResult:
    if not data:
        return ParseResult(kind="text", text=original)
    if str(data.get("type") or "") == "text":
        return ParseResult(kind="text", text=str(data.get("content") or ""))
    calls = data.get("calls")
    if not isinstance(calls, list):
        calls = data.get("tool_calls")
    if str(data.get("type") or "") == "tool_calls" or isinstance(calls, list):
        if isinstance(calls, list) and calls:
            return ParseResult(kind="tool_calls", calls=_raw_calls(calls))
    return ParseResult(kind="text", text=original)


def _raw_calls(calls: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else call
        name = str(fn.get("name") or call.get("name") or "").strip()
        arguments = fn.get("arguments") if "arguments" in fn else call.get("arguments")
        items.append({"name": name, "arguments": arguments})
    return items


def _normalize(
    parsed: ParseResult,
    original: str,
    tool_names: list[str],
    named: str | None,
) -> ParseResult:
    if parsed.kind != "tool_calls":
        return parsed
    allowed = set(tool_names)
    built: list[dict[str, str]] = []
    for call in parsed.calls:
        name = str(call.get("name") or "").strip()
        if named and name != named:
            continue
        if allowed and name not in allowed:
            return ParseResult(kind="text", text=original, degraded=True)
        arguments = _dump_arguments(call.get("arguments"))
        if arguments is None:
            continue
        built.append({"id": "call_" + secrets.token_hex(6), "name": name, "arguments": arguments})
    if not built:
        return ParseResult(kind="text", text=original, degraded=True)
    return ParseResult(kind="tool_calls", calls=built)


def _dump_arguments(value: Any) -> str | None:
    if isinstance(value, str):
        try:
            json.loads(value)
        except json.JSONDecodeError:
            return None
        return value
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "{}"
    return None
