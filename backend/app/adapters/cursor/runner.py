from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

from app.adapters.cursor.account import friendly_cursor_error, read_sdk_store
from app.adapters.cursor.policy import cursor_run_policy
from app.engine.errors import classify_engine_error
from app.engine.types import EngineResult
from app.models import normalize_cursor_model

log = logging.getLogger("app.adapters.cursor.runner")

# 测试可替换。正式路径在首次调用时填入 cursor_sdk.AsyncAgent。
AsyncAgent: Any = None


def cursor_api_key() -> str:
    from app.config import get_settings

    try:
        token = get_settings().cursor_token()
    except Exception:
        token = ""
    key = (token or os.environ.get("CURSOR_API_KEY") or "").strip()
    if key:
        return key
    store = read_sdk_store() or {}
    return str(store.get("api_key") or "").strip()


def describe_cursor() -> dict[str, Any]:
    cli_present = shutil.which("agent") is not None
    try:
        import cursor_sdk
    except Exception as exc:
        return {
            "ok": False,
            "installed": False,
            "auth": "missing",
            "cli_present": cli_present,
            "profile": None,
            "expires_at": "",
            "error": f"未安装 cursor-sdk：{exc}",
        }
    store = read_sdk_store() or {}
    token = cursor_api_key()
    env_key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    try:
        from app.config import get_settings

        secret_key = get_settings().cursor_token()
    except Exception:
        secret_key = ""
    if secret_key or env_key:
        auth = "api_key"
    elif store.get("api_key"):
        auth = "sdk_store"
    else:
        auth = "missing"
    profile = None
    if store.get("email"):
        profile = {"email": store["email"], "label": store["email"]}
    return {
        "ok": bool(token),
        "installed": True,
        "cli_present": cli_present,
        "sdk_version": getattr(cursor_sdk, "__version__", "") or "",
        "auth": auth,
        "profile": profile,
        "expires_at": str(store.get("expires_at") or ""),
    }


def _options(cwd: Path, model: str):
    from cursor_sdk import AgentOptions, LocalAgentOptions

    policy = cursor_run_policy()
    return AgentOptions(
        api_key=cursor_api_key(),
        model=normalize_cursor_model(model),
        tools=policy["tools"],
        disallowed_tools=policy["disallowed_tools"],
        local=LocalAgentOptions(cwd=str(cwd), setting_sources=policy["setting_sources"]),
    )


async def _launch_bridge(cwd: str):
    from cursor_sdk import AsyncClient

    return await AsyncClient.launch_bridge(workspace=cwd)


def _agent_cls() -> Any:
    global AsyncAgent
    if AsyncAgent is None:
        from cursor_sdk import AsyncAgent as cls

        AsyncAgent = cls
    return AsyncAgent


class _CursorBridgePool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: Any = None
        self._cwd = ""

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop and self._thread and self._thread.is_alive():
                return self._loop
            ready = threading.Event()
            loop_box: dict[str, asyncio.AbstractEventLoop] = {}

            def work() -> None:
                if sys.platform == "win32":
                    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop_box["loop"] = loop
                ready.set()
                loop.run_forever()

            thread = threading.Thread(target=work, name="cursor-bridge", daemon=True)
            thread.start()
            if not ready.wait(timeout=8):
                raise RuntimeError("Cursor 工作线程启动失败")
            self._thread = thread
            self._loop = loop_box["loop"]
            return self._loop

    def _submit(self, coro: Any, timeout_sec: float) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._ensure_loop())
        return future.result(timeout=timeout_sec)

    async def _close_client(self) -> None:
        client = self._client
        self._client = None
        self._cwd = ""
        if client is None:
            return
        closer = getattr(client, "aclose", None)
        if closer is None:
            return
        try:
            await closer()
        except Exception as exc:
            log.warning("关闭 Cursor bridge 失败：%s", exc)

    async def _client_for(self, cwd: str, *, force: bool = False) -> Any:
        if force or self._client is None or self._cwd != cwd:
            started = time.perf_counter()
            await self._close_client()
            self._client = await _launch_bridge(cwd)
            self._cwd = cwd
            log.info("Cursor bridge 已就绪（%.1fs）cwd=%s", time.perf_counter() - started, cwd)
        return self._client

    async def _run_once(self, prompt: str, model: str, cwd: Path, *, force_bridge: bool = False) -> EngineResult:
        client = await self._client_for(str(cwd), force=force_bridge)
        created = time.perf_counter()
        agent = await _agent_cls().create(_options(cwd, model), client=client)
        session_id = getattr(agent, "agent_id", "") or ""
        log.info("Cursor agent 已创建（%.1fs）model=%s", time.perf_counter() - created, model)
        texts: list[str] = []
        result: Any = None
        try:
            sent = time.perf_counter()
            run = await agent.send(prompt)
            async for message in run.stream():
                kind = str(getattr(message, "type", "") or "")
                if kind in {"thinking", "tool_call", "status"}:
                    continue
                if kind == "assistant":
                    content = getattr(getattr(message, "message", None), "content", ()) or ()
                    for block in content:
                        text = getattr(block, "text", None)
                        if isinstance(text, str) and text:
                            texts.append(text)
            result = await run.wait()
            log.info("Cursor 生文结束（%.1fs）", time.perf_counter() - sent)
        finally:
            closer = getattr(agent, "close", None)
            if closer is not None:
                await closer()
        status = str(getattr(result, "status", "") or "")
        result_text = str(getattr(result, "result", "") or "")
        if status == "error":
            error = friendly_cursor_error(result_text or "Cursor 执行失败")
            return EngineResult(
                ok=False,
                error=error,
                error_class=classify_engine_error(error),
                engine="cursor",
                model=model,
                session_id=session_id,
            )
        answer = (result_text or "".join(texts)).strip()
        if not answer:
            return EngineResult(ok=False, error="Cursor 没有返回文本", error_class="engine", engine="cursor", model=model)
        return EngineResult(ok=True, text=answer, engine="cursor", model=model, session_id=session_id)

    async def _run(self, prompt: str, model: str, cwd: Path) -> EngineResult:
        try:
            return await self._run_once(prompt, model, cwd)
        except Exception as exc:
            log.warning("Cursor 复用 bridge 失败，重拉一次：%s", exc)
            return await self._run_once(prompt, model, cwd, force_bridge=True)

    def run(self, prompt: str, model: str, cwd: Path, timeout_sec: int) -> EngineResult:
        try:
            return self._submit(self._run(prompt, model, cwd), timeout_sec + 8)
        except TimeoutError:
            return EngineResult(ok=False, error="Cursor 超时", error_class="timeout", engine="cursor", model=model)

    def warmup(self, cwd: Path) -> None:
        def work() -> None:
            try:
                self._submit(self._client_for(str(cwd)), 45)
            except Exception as exc:
                log.warning("预热 Cursor bridge 失败：%s", exc)

        threading.Thread(target=work, name="cursor-warmup", daemon=True).start()

    def reset(self) -> None:
        loop = self._loop
        if loop and loop.is_running():
            try:
                self._submit(self._close_client(), 8)
            except Exception:
                self._client = None
                self._cwd = ""
        else:
            self._client = None
            self._cwd = ""


_POOL = _CursorBridgePool()


def reset_cursor_pool() -> None:
    _POOL.reset()


def warmup_cursor(cwd: Path | None = None) -> None:
    from app.config import get_settings

    path = cwd or get_settings().workspace_path()
    path.mkdir(parents=True, exist_ok=True)
    _POOL.warmup(path)


def run_cursor(
    prompt: str,
    *,
    model: str,
    cwd: Path,
    timeout_sec: int,
    max_turns: int,
) -> EngineResult:
    info = describe_cursor()
    if not info.get("installed"):
        return EngineResult(ok=False, error="未安装 cursor-sdk", error_class="engine", engine="cursor", model=model)
    if not info.get("ok"):
        return EngineResult(ok=False, error="Cursor 未登录", error_class="login", engine="cursor", model=model)
    cwd.mkdir(parents=True, exist_ok=True)
    key = cursor_api_key()
    if key:
        os.environ["CURSOR_API_KEY"] = key
    started = time.perf_counter()
    try:
        result = _POOL.run(prompt, model, cwd, timeout_sec)
    except Exception as exc:
        return EngineResult(
            ok=False,
            error=friendly_cursor_error(str(exc)),
            error_class=classify_engine_error(str(exc)),
            engine="cursor",
            model=model,
        )
    log.info("Cursor 整轮 %.1fs model=%s ok=%s", time.perf_counter() - started, model, result.ok)
    return result
