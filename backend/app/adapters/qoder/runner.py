from __future__ import annotations

import asyncio
import inspect
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from app.adapters.qoder.account import friendly_qoder_error
from app.adapters.qoder.policy import DENY_MESSAGE, qoder_run_policy
from app.engine.errors import classify_engine_error
from app.engine.types import EngineResult

log = logging.getLogger("app.adapters.qoder.runner")

# 测试可替换。正式路径在首次调用时填入 SDK。
query: Any = None
QoderSDKClient: Any = None


def _token_env() -> str | None:
    for key in ("QODER_PERSONAL_ACCESS_TOKEN", "QODERCN_PERSONAL_ACCESS_TOKEN"):
        if os.environ.get(key):
            return key
    return None


def _decode_cli(raw: bytes | None) -> str:
    data = raw or b""
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


_CLI_STATUS: dict[str, Any] = {"at": 0.0, "profile": None, "checked": False}


def reset_cli_profile() -> None:
    _CLI_STATUS.update({"at": 0.0, "profile": None, "checked": False})


def _qodercli_profile(refresh: bool = False) -> dict[str, str] | None:
    now = time.time()
    if not refresh and _CLI_STATUS["checked"] and now - float(_CLI_STATUS["at"] or 0) < 90:
        profile = _CLI_STATUS.get("profile")
        return profile if isinstance(profile, dict) else None
    exe = next((name for name in ("qodercli", "qoderclicn", "qoder", "qodercn") if shutil.which(name)), None)
    if not exe:
        _CLI_STATUS.update({"at": now, "profile": None, "checked": True})
        return None
    try:
        proc = subprocess.run([exe, "status"], capture_output=True, timeout=20)
    except Exception as exc:
        log.warning("读取 qodercli status 失败：%s", exc)
        _CLI_STATUS.update({"at": now, "profile": None, "checked": True})
        return None
    text = _decode_cli(proc.stdout) + "\n" + _decode_cli(proc.stderr)
    username = ""
    email = ""
    for line in text.splitlines():
        if line.lower().startswith("username:"):
            username = line.split(":", 1)[1].strip()
        elif line.lower().startswith("email:"):
            email = line.split(":", 1)[1].strip()
    profile = None
    if proc.returncode == 0 and (username or email):
        profile = {"username": username, "email": email, "label": username or email}
    _CLI_STATUS.update({"at": now, "profile": profile, "checked": True})
    return profile


def describe_qoder() -> dict[str, Any]:
    cli_present = any(shutil.which(name) for name in ("qodercli", "qoderclicn", "qoder", "qodercn"))
    try:
        import qoder_agent_sdk
    except Exception as exc:
        return {
            "ok": False,
            "installed": False,
            "auth": "missing",
            "cli_present": cli_present,
            "profile": None,
            "error": f"未安装 qoder-agent-sdk：{exc}",
        }
    token_key = _token_env()
    profile = _qodercli_profile()
    auth = "pat" if token_key else ("qodercli" if profile else "missing")
    return {
        "ok": bool(token_key or profile),
        "installed": True,
        "cli_present": cli_present or bool(profile),
        "sdk_version": getattr(qoder_agent_sdk, "__version__", "") or "",
        "auth": auth,
        "profile": profile,
    }


def qoder_auth():
    from qoder_agent_sdk import access_token_from_env, qodercli_auth

    key = _token_env()
    if key:
        return access_token_from_env(env_var=key)
    return qodercli_auth()


def _qoder_options(cwd: Path, model: str, max_turns: int):
    from qoder_agent_sdk import PermissionResultDeny, QoderAgentOptions

    policy = qoder_run_policy(max_turns=max_turns)

    async def can_use_tool(tool_name: str, tool_input: dict, _ctx):
        return PermissionResultDeny(message=DENY_MESSAGE)

    kwargs: dict[str, Any] = {
        "auth": qoder_auth(),
        "cwd": str(cwd),
        "system_prompt": {
            "type": "preset",
            "preset": "qodercli",
            "append": "You are only a completion model. Do not use engine tools.",
        },
        "tools": {"type": "preset", "preset": "qodercli"},
        "allowed_tools": policy["allowed_tools"],
        "disallowed_tools": policy["disallowed_tools"],
        "permission_mode": "default",
        "model": (model or "").strip() or "qmodel_38max",
        "can_use_tool": can_use_tool,
        "max_turns": policy["max_turns"],
        "resume": None,
        "setting_sources": [],
        "include_partial_messages": True,
    }
    if os.environ.get("QODER_CLI_PATH"):
        kwargs["cli_path"] = Path(os.environ["QODER_CLI_PATH"])
    params = inspect.signature(QoderAgentOptions).parameters
    if "skills" in params:
        kwargs["skills"] = policy["skills"]
    return QoderAgentOptions(**{key: value for key, value in kwargs.items() if key in params})


def _query_fn() -> Any:
    global query
    if query is None:
        from qoder_agent_sdk import query as fn

        query = fn
    return query


def _client_cls() -> Any:
    global QoderSDKClient
    if QoderSDKClient is None:
        from qoder_agent_sdk import QoderSDKClient as cls

        QoderSDKClient = cls
    return QoderSDKClient


def _result_from_messages(messages: list[Any], *, model: str) -> EngineResult:
    texts: list[str] = []
    error = None
    result_text = ""
    session_id = ""
    for message in messages:
        name = type(message).__name__
        if name in {"StreamEvent", "ThinkingBlock"}:
            continue
        if name == "AssistantMessage":
            for block in getattr(message, "content", ()) or ():
                if type(block).__name__ in {"ToolUseBlock", "ThinkingBlock"}:
                    continue
                text = getattr(block, "text", None)
                if isinstance(text, str) and text.strip():
                    texts.append(text)
            continue
        if name != "ResultMessage":
            continue
        session_id = getattr(message, "session_id", "") or session_id
        if getattr(message, "is_error", False):
            raw = (getattr(message, "errors", None) or [getattr(message, "result", None)] or ["Qoder 执行失败"])[0]
            error = friendly_qoder_error(raw)
        result_text = getattr(message, "result", "") or ""
    if error:
        return EngineResult(
            ok=False,
            error=error,
            error_class=classify_engine_error(error),
            engine="qoder",
            model=model,
            session_id=session_id,
        )
    answer = (result_text or "\n\n".join(texts)).strip()
    if not answer:
        return EngineResult(ok=False, error="Qoder 没有返回文本", error_class="engine", engine="qoder", model=model)
    return EngineResult(ok=True, text=answer, engine="qoder", model=model, session_id=session_id)


class _QoderSessionPool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._idle: Any = None
        self._idle_key: tuple[str, str, int] | None = None

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

            thread = threading.Thread(target=work, name="qoder-bridge", daemon=True)
            thread.start()
            if not ready.wait(timeout=8):
                raise RuntimeError("Qoder 工作线程启动失败")
            self._thread = thread
            self._loop = loop_box["loop"]
            return self._loop

    def _submit(self, coro: Any, timeout_sec: float) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._ensure_loop())
        return future.result(timeout=timeout_sec)

    async def _close_idle(self) -> None:
        client = self._idle
        self._idle = None
        self._idle_key = None
        if client is None:
            return
        closer = getattr(client, "disconnect", None) or getattr(client, "aclose", None)
        if closer is None:
            return
        try:
            await closer()
        except Exception as exc:
            log.warning("关闭 Qoder CLI 失败：%s", exc)

    async def _ensure_idle(self, cwd: Path, model: str, max_turns: int) -> Any:
        key = (str(cwd), model, max_turns)
        if self._idle is not None and self._idle_key == key:
            return self._idle
        started = time.perf_counter()
        await self._close_idle()
        client = _client_cls()(_qoder_options(cwd, model, max_turns))
        await client.connect()
        self._idle = client
        self._idle_key = key
        log.info("Qoder CLI 已预热（%.1fs）cwd=%s", time.perf_counter() - started, cwd)
        return client

    async def _take_idle(self, cwd: Path, model: str, max_turns: int) -> Any:
        key = (str(cwd), model, max_turns)
        if self._idle is None or self._idle_key != key:
            return None
        client = self._idle
        self._idle = None
        self._idle_key = None
        return client

    async def _consume(self, agen: Any, timeout_sec: int, model: str) -> EngineResult:
        messages: list[Any] = []

        async def read() -> None:
            async for message in agen:
                messages.append(message)
                if type(message).__name__ == "ResultMessage":
                    return

        try:
            await asyncio.wait_for(read(), timeout=timeout_sec)
        finally:
            closer = getattr(agen, "aclose", None)
            if closer is not None:
                await closer()
        return _result_from_messages(messages, model=model)

    async def _run_query(self, prompt: str, model: str, cwd: Path, timeout_sec: int, max_turns: int) -> EngineResult:
        started = time.perf_counter()
        agen = _query_fn()(prompt=prompt, options=_qoder_options(cwd, model, max_turns))
        if inspect.isawaitable(agen):
            agen = await agen
        result = await self._consume(agen, timeout_sec, model)
        log.info("Qoder query 结束（%.1fs）ok=%s", time.perf_counter() - started, result.ok)
        return result

    async def _run_client(self, client: Any, prompt: str, model: str, timeout_sec: int) -> EngineResult:
        started = time.perf_counter()
        try:
            await client.query(prompt)
            result = await self._consume(client.receive_response(), timeout_sec, model)
            log.info("Qoder 预热会话结束（%.1fs）ok=%s", time.perf_counter() - started, result.ok)
            return result
        finally:
            closer = getattr(client, "disconnect", None)
            if closer is not None:
                try:
                    await closer()
                except Exception as exc:
                    log.warning("关闭已用 Qoder 会话失败：%s", exc)

    async def _run_once(self, prompt: str, model: str, cwd: Path, timeout_sec: int, max_turns: int) -> EngineResult:
        client = await self._take_idle(cwd, model, max_turns)
        if client is not None:
            return await self._run_client(client, prompt, model, timeout_sec)
        return await self._run_query(prompt, model, cwd, timeout_sec, max_turns)

    async def _run(self, prompt: str, model: str, cwd: Path, timeout_sec: int, max_turns: int) -> EngineResult:
        try:
            result = await self._run_once(prompt, model, cwd, timeout_sec, max_turns)
        except Exception as exc:
            log.warning("Qoder 复用失败，改走一次性 query：%s", exc)
            await self._close_idle()
            result = await self._run_query(prompt, model, cwd, timeout_sec, max_turns)
        if result.ok:
            try:
                await self._ensure_idle(cwd, model, max_turns)
            except Exception as exc:
                log.warning("预热下一轮 Qoder CLI 失败：%s", exc)
        return result

    def run(self, prompt: str, model: str, cwd: Path, timeout_sec: int, max_turns: int) -> EngineResult:
        try:
            return self._submit(self._run(prompt, model, cwd, timeout_sec, max_turns), timeout_sec + 8)
        except TimeoutError:
            return EngineResult(ok=False, error="Qoder 超时", error_class="timeout", engine="qoder", model=model)

    def warmup(self, cwd: Path, model: str, max_turns: int) -> None:
        def work() -> None:
            try:
                self._submit(self._ensure_idle(cwd, model, max_turns), 45)
            except Exception as exc:
                log.warning("预热 Qoder CLI 失败：%s", exc)

        threading.Thread(target=work, name="qoder-warmup", daemon=True).start()

    def reset(self) -> None:
        loop = self._loop
        if loop and loop.is_running():
            try:
                self._submit(self._close_idle(), 8)
            except Exception:
                self._idle = None
                self._idle_key = None
        else:
            self._idle = None
            self._idle_key = None


_POOL = _QoderSessionPool()


def reset_qoder_pool() -> None:
    _POOL.reset()


def warmup_qoder(cwd: Path | None = None, model: str | None = None, max_turns: int | None = None) -> None:
    path = cwd
    chosen_model = model
    turns = max_turns
    if path is None or not chosen_model or turns is None:
        from app.config import get_settings

        settings = get_settings()
        path = path or settings.workspace_path()
        chosen_model = chosen_model or settings.default_engine_model("qoder")
        turns = turns or settings.max_turns()
    path.mkdir(parents=True, exist_ok=True)
    _POOL.warmup(path, chosen_model, turns)


def run_qoder(
    prompt: str,
    *,
    model: str,
    cwd: Path,
    timeout_sec: int,
    max_turns: int,
) -> EngineResult:
    info = describe_qoder()
    if not info.get("installed"):
        return EngineResult(ok=False, error="未安装 qoder-agent-sdk", error_class="engine", engine="qoder", model=model)
    if not info.get("ok"):
        return EngineResult(ok=False, error="Qoder 未登录", error_class="login", engine="qoder", model=model)
    cwd.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        result = _POOL.run(prompt, model, cwd, timeout_sec, max_turns)
    except Exception as exc:
        return EngineResult(
            ok=False,
            error=friendly_qoder_error(str(exc)),
            error_class=classify_engine_error(str(exc)),
            engine="qoder",
            model=model,
        )
    log.info("Qoder 整轮 %.1fs model=%s ok=%s", time.perf_counter() - started, model, result.ok)
    return result
