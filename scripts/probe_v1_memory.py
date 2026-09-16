"""Hit the live proxy with a Hermes-shaped memory turn. Prints no secrets."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
ATTEMPTS = 3

MEMORY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory",
            "description": (
                "Save durable facts to persistent memory. "
                "Single change: action=add, target=user or memory, content=the fact. "
                "User name belongs in target=user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "replace", "remove"]},
                    "target": {"type": "string", "enum": ["memory", "user"]},
                    "content": {"type": "string"},
                    "old_text": {"type": "string"},
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string", "enum": ["add", "replace", "remove"]},
                                "content": {"type": "string"},
                                "old_text": {"type": "string"},
                            },
                            "required": ["action"],
                        },
                    },
                },
                "required": ["target"],
            },
        },
    }
]


def _secrets() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / "config" / "secrets.env"
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _request(
    opener: urllib.request.OpenerDirector,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"error": {"message": raw[:300]}}
        return exc.code, parsed


def _summarize(payload: dict) -> dict:
    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        return {"ok": False, "error": error.get("message"), "type": error.get("type")}
    choices = payload.get("choices") or []
    if not choices:
        return {"ok": False, "error": "empty choices"}
    choice = choices[0]
    message = choice.get("message") or {}
    calls = message.get("tool_calls") or []
    tools = []
    for item in calls:
        fn = item.get("function") if isinstance(item, dict) else {}
        tools.append(
            {
                "name": fn.get("name"),
                "arguments": (fn.get("arguments") or "")[:180],
            }
        )
    content = message.get("content")
    return {
        "ok": True,
        "model": payload.get("model"),
        "finish_reason": choice.get("finish_reason"),
        "content": (content or "")[:180],
        "tools": tools,
    }


def main() -> int:
    secrets = _secrets()
    proxy = (secrets.get("PROXY_API_KEY") or "").strip()
    if not proxy:
        print("PROXY_API_KEY missing")
        return 2
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    login_status, _ = _request(
        opener,
        "POST",
        "/api/login",
        body={"username": "admin", "password": secrets.get("SETTINGS_PASSWORD") or "admin"},
    )
    if login_status != 200:
        print("login_failed", login_status)
        return 2

    _, before = _request(opener, "GET", "/api/parse-stats")
    results = []
    for index in range(1, ATTEMPTS + 1):
        status, payload = _request(
            opener,
            "POST",
            "/v1/chat/completions",
            body={
                "model": "default",
                "messages": [
                    {
                        "role": "user",
                        "content": f"记住：我的名字叫测用户{index}。这是需要写入长期记忆的事实，请调用 memory 工具保存。",
                    }
                ],
                "tools": MEMORY_TOOLS,
                "tool_choice": "auto",
            },
            headers={"Authorization": f"Bearer {proxy}"},
            timeout=200,
        )
        summary = _summarize(payload)
        summary["attempt"] = index
        summary["http"] = status
        results.append(summary)
        print(json.dumps(summary, ensure_ascii=False))
        names = [item.get("name") for item in summary.get("tools") or []]
        if status == 200 and summary.get("finish_reason") == "tool_calls" and "memory" in names:
            break

    _, after = _request(opener, "GET", "/api/parse-stats")
    print(
        json.dumps(
            {
                "parse_before": before.get("counts"),
                "parse_after": after.get("counts"),
                "last": after.get("last"),
            },
            ensure_ascii=False,
        )
    )
    ok = any(
        item.get("finish_reason") == "tool_calls"
        and "memory" in [tool.get("name") for tool in item.get("tools") or []]
        for item in results
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
