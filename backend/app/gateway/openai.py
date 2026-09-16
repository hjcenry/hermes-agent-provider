from __future__ import annotations

import hmac
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import Settings
from app.engine.dispatch import run_engine
from app.models import list_public_models, parse_model, public_id
from app.translator.openai_out import completion_payload, iter_sse
from app.translator.parse import parse_output
from app.translator.prompt import build_prompt
from app.translator.stats import record_parse

router = APIRouter()

_ERROR_HTTP = {
    "login": (401, "invalid_request_error"),
    "quota": (429, "rate_limit_error"),
    "timeout": (504, "server_error"),
    "engine": (502, "server_error"),
    "unknown": (502, "server_error"),
}


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _bearer_ok(request: Request, settings: Settings) -> bool:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return False
    got = header[7:].strip().encode("utf-8")
    expected = settings.proxy_api_key().encode("utf-8")
    if not expected or len(got) != len(expected):
        return False
    return hmac.compare_digest(got, expected)


def _error(status: int, message: str, typ: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"message": message, "type": typ}})


def _unauthorized() -> JSONResponse:
    return _error(401, "Invalid API key", "invalid_request_error")


def _normalize_tools(body: dict[str, Any]) -> list[dict[str, Any]]:
    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        return [item for item in tools if isinstance(item, dict)]
    functions = body.get("functions")
    if isinstance(functions, list):
        return [{"type": "function", "function": item} for item in functions if isinstance(item, dict)]
    return []


def _normalize_tool_choice(raw: Any) -> str:
    if raw in (None, ""):
        return "auto"
    if isinstance(raw, str):
        return raw.strip() or "auto"
    if isinstance(raw, dict):
        fn = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        name = str(fn.get("name") or "").strip()
        return name or "required"
    return "auto"


def _tool_names(tools: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for tool in tools:
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = str(fn.get("name") or "").strip()
        if name:
            names.append(name)
    return names


@router.get("/v1/models")
def list_models(request: Request) -> Any:
    settings = _settings(request)
    if not _bearer_ok(request, settings):
        return _unauthorized()
    return {"object": "list", "data": list_public_models(settings)}


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    settings = _settings(request)
    if not _bearer_ok(request, settings):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _error(400, "请求体必须是 JSON", "invalid_request_error")
    if not isinstance(body, dict):
        return _error(400, "请求体必须是 JSON 对象", "invalid_request_error")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return _error(400, "messages 不能为空", "invalid_request_error")
    try:
        engine, model = parse_model(str(body.get("model") or ""), settings)
    except ValueError as exc:
        return _error(400, str(exc), "invalid_request_error")
    tools = _normalize_tools(body)
    choice = _normalize_tool_choice(body.get("tool_choice"))
    prompt = build_prompt(messages, tools, choice)
    result = run_engine(prompt, engine=engine, model=model)
    if not result.ok:
        status, typ = _ERROR_HTTP.get(result.error_class or "unknown", (502, "server_error"))
        return _error(status, result.error or "引擎失败", typ)
    parsed = parse_output(result.text, tool_names=_tool_names(tools), tool_choice=choice)
    record_parse(parsed)
    shown = public_id(engine, model)
    payload = completion_payload(
        model=shown,
        text=parsed.text if parsed.kind == "text" else None,
        calls=parsed.calls if parsed.kind == "tool_calls" else None,
        completion_id="chatcmpl-" + uuid.uuid4().hex,
        created=int(time.time()),
    )
    if body.get("stream") is True:
        return StreamingResponse(iter_sse(payload), media_type="text/event-stream")
    return payload
