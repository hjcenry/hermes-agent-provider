from __future__ import annotations

import json
import os
from typing import Any

from app.engine.types import EngineResult

_UNSET = object()
_FAKE: Any = _UNSET
_FAKE_ERROR_TEXT = {
    "login": "引擎未登录，请先在设置页加载令牌或完成本机登录。",
    "quota": "额度已用完，请稍后或在设置页切换引擎。",
    "timeout": "引擎超时",
    "engine": "引擎失败",
}


def set_fake_engine(payload: dict[str, Any] | None) -> None:
    global _FAKE
    _FAKE = payload


def run_engine(prompt: str, *, engine: str, model: str) -> EngineResult:
    fake = _env_fake() if _FAKE is _UNSET else _FAKE
    if fake is not None:
        return _run_fake(fake, engine=engine, model=model)
    name = (engine or "").strip().lower()
    if name == "qoder":
        from app.adapters.qoder.runner import run_qoder
        from app.config import get_settings

        settings = get_settings()
        return run_qoder(
            prompt,
            model=model,
            cwd=settings.workspace_path(),
            timeout_sec=settings.timeout_sec(),
            max_turns=settings.max_turns(),
        )
    if name == "cursor":
        from app.adapters.cursor.runner import run_cursor
        from app.config import get_settings

        settings = get_settings()
        return run_cursor(
            prompt,
            model=model,
            cwd=settings.workspace_path(),
            timeout_sec=settings.timeout_sec(),
            max_turns=settings.max_turns(),
        )
    return EngineResult(
        ok=False,
        error="未知引擎",
        error_class="engine",
        engine=engine,
        model=model,
    )


def _run_fake(fake: dict[str, Any], *, engine: str, model: str) -> EngineResult:
    mode = str(fake.get("mode") or "")
    if mode == "text":
        return EngineResult(ok=True, text=str(fake.get("text") or ""), engine=engine, model=model)
    if mode == "tools":
        body = {"type": "tool_calls", "calls": list(fake.get("calls") or [])}
        text = "```hermes-proxy\n" + json.dumps(body, ensure_ascii=False) + "\n```"
        return EngineResult(ok=True, text=text, engine=engine, model=model)
    if mode == "error":
        cls = str(fake.get("class") or "engine")
        return EngineResult(
            ok=False,
            error=_FAKE_ERROR_TEXT.get(cls, cls),
            error_class=cls,
            engine=engine,
            model=model,
        )
    return EngineResult(ok=False, error="未知假引擎模式", error_class="engine", engine=engine, model=model)


def _env_fake() -> dict[str, Any] | None:
    raw = (
        os.environ.get("HERMES_AGENT_PROVIDER_FAKE")
        or os.environ.get("CURSOR_TO_OPENAI_FAKE")
        or os.environ.get("ENGINE_RELAY_FAKE")
        or os.environ.get("J2000_HERMES_FAKE")
        or ""
    ).strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
