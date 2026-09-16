from __future__ import annotations

import json
from typing import Any, Iterator

_CHUNK = 40


def completion_payload(
    *,
    model: str,
    text: str | None,
    calls: list[dict[str, str]] | None,
    completion_id: str,
    created: int,
) -> dict[str, Any]:
    if calls:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": item["id"],
                    "type": "function",
                    "function": {"name": item["name"], "arguments": item["arguments"]},
                }
                for item in calls
            ],
        }
        finish = "tool_calls"
    else:
        message = {"role": "assistant", "content": text or ""}
        finish = "stop"
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def iter_sse(body: dict[str, Any]) -> Iterator[str]:
    choice = body["choices"][0]
    message = choice["message"]
    yield _chunk(body, {"role": "assistant"})
    if message.get("tool_calls"):
        yield _chunk(
            body,
            {
                "tool_calls": [
                    {
                        "index": index,
                        "id": item["id"],
                        "type": "function",
                        "function": item["function"],
                    }
                    for index, item in enumerate(message["tool_calls"])
                ]
            },
        )
        yield _chunk(body, {}, finish="tool_calls")
    else:
        text = str(message.get("content") or "")
        for start in range(0, len(text), _CHUNK) or [0]:
            piece = text[start : start + _CHUNK]
            if piece:
                yield _chunk(body, {"content": piece})
        yield _chunk(body, {}, finish="stop")
    yield "data: [DONE]\n\n"


def _chunk(body: dict[str, Any], delta: dict[str, Any], finish: str | None = None) -> str:
    payload = {
        "id": body["id"],
        "object": "chat.completion.chunk",
        "created": body["created"],
        "model": body["model"],
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
