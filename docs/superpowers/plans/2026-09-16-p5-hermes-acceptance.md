# P5 Hermes 验收收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口第一期 P5：把规格第 18 节必须项补成可测行为，设置页露出解析计数，README 写成 Hermes 可跟做的接入步骤。

**Architecture:** `/v1` 仍先跑引擎再解析。本阶段不改流式策略、不做嵌套 Agent。缺口集中在三处：假引擎错误文案（401/429 人能读懂）、`parse_output` 标记降级并累计到进程内统计、设置页只读展示。

**Tech Stack:** FastAPI、pytest、React/Vite、现有 Cookie `/api` 与 Bearer `/v1`。

## Global Constraints

- 默认只听 `127.0.0.1:8765`；`/v1` Bearer，`/api` Cookie。
- 引擎工具第一期全关；不 resume 引擎；SSE 仍先收齐再重放。
- 不引导把 Hermes 辅助模型指到本代理。
- 不提交 git（除非用户明确要求）。
- 测试不打真实云端、不把真实 `PROXY_API_KEY` 写进仓库或聊天。

---

### Task 1: `/v1` 未登录 401、额度用尽 429 且文案可读

**Files:**
- Modify: `backend/tests/test_gateway.py`
- Modify: `backend/app/engine/dispatch.py`
- Test: `backend/tests/test_gateway.py`

**Interfaces:**
- Consumes: `set_fake_engine({"mode":"error","class":"login"|"quota"})`；`_ERROR_HTTP` 已把 `login→401`、`quota→429`
- Produces: `EngineResult.error` 为中文可读句；`error_class` 仍为 `login` / `quota`

- [ ] **Step 1: Write the failing test**

在 `test_gateway.py` 追加：

```python
def test_chat_login_maps_to_401(hermes_root):
    set_fake_engine({"mode": "error", "class": "login"})
    try:
        client = _client(hermes_root)
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 401
        body = response.json()["error"]
        assert body["type"] == "invalid_request_error"
        assert "未登录" in body["message"]
    finally:
        set_fake_engine(None)


def test_chat_quota_message_is_readable(hermes_root):
    set_fake_engine({"mode": "error", "class": "quota"})
    try:
        client = _client(hermes_root)
        response = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 429
        assert "额度" in response.json()["error"]["message"]
    finally:
        set_fake_engine(None)
```

保留现有 `test_chat_quota_maps_to_429`。

- [ ] **Step 2: Run test to verify it fails**

Run: `backend\.venv\Scripts\python -m pytest tests\test_gateway.py::test_chat_login_maps_to_401 tests\test_gateway.py::test_chat_quota_message_is_readable -q --tb=short`

Expected: FAIL because fake error message is the class name (`login` / `quota`), not Chinese.

- [ ] **Step 3: Write minimal implementation**

In `dispatch.py` `_run_fake`, map class to readable text:

```python
_FAKE_ERROR_TEXT = {
    "login": "引擎未登录，请先在设置页加载令牌或完成本机登录。",
    "quota": "额度已用完，请稍后或在设置页切换引擎。",
    "timeout": "引擎超时",
    "engine": "引擎失败",
}
```

`mode == "error"` 时：`error=_FAKE_ERROR_TEXT.get(cls, cls)`，`error_class=cls`。

- [ ] **Step 4: Run test to verify it passes**

Run: `backend\.venv\Scripts\python -m pytest tests\test_gateway.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

Skip unless the user asks.

---

### Task 2: 解析结果标记降级 + 进程内计数

**Files:**
- Create: `backend/tests/test_parse_stats.py`
- Modify: `backend/app/translator/parse.py`
- Create: `backend/app/translator/stats.py`
- Modify: `backend/app/gateway/openai.py`
- Modify: `backend/app/api/settings_routes.py`
- Test: `backend/tests/test_parse_stats.py`、`backend/tests/test_translator.py`

**Interfaces:**
- Consumes: `parse_output(raw, tool_names, tool_choice) -> ParseResult`
- Produces:
  - `ParseResult.degraded: bool`
  - `record_parse(parsed: ParseResult) -> None`
  - `public_parse_stats() -> dict` 形状：

```python
{
    "ok": True,
    "last": {
        "kind": "tool_calls" | "text" | "degraded",  # last 对外 kind：degraded 当 parsed.degraded
        "label": "成功围栏" | "纯文本" | "降级文本",
        "tools": ["memory"],
        "preview": "最多 160 字",
    },
    "counts": {"fence_ok": int, "text": int, "degraded": int},
}
```

  - `reset_parse_stats() -> None` 供测试
  - `GET /api/parse-stats` Cookie 鉴权，返回 `public_parse_stats()`

- [ ] **Step 1: Write the failing test**

`test_translator.py` 给未知工具名补 `assert out.degraded is True`；半截 JSON `assert out.degraded is False`。

`test_parse_stats.py`：

```python
from fastapi.testclient import TestClient
from app.config import load_settings
from app.engine.dispatch import set_fake_engine
from app.main import create_app
from app.translator.parse import parse_output
from app.translator.stats import public_parse_stats, record_parse, reset_parse_stats

AUTH = {"Authorization": "Bearer test-proxy-key"}


def test_record_parse_counts_fence_and_degraded():
    reset_parse_stats()
    ok = parse_output(
        '```hermes-proxy\n{"type":"tool_calls","calls":[{"name":"memory","arguments":{}}]}\n```',
        tool_names=["memory"],
    )
    bad = parse_output(
        '```hermes-proxy\n{"type":"tool_calls","calls":[{"name":"nope","arguments":{}}]}\n```',
        tool_names=["memory"],
    )
    record_parse(ok)
    record_parse(bad)
    stats = public_parse_stats()
    assert stats["counts"] == {"fence_ok": 1, "text": 0, "degraded": 1}
    assert stats["last"]["kind"] == "degraded"
    assert stats["last"]["label"] == "降级文本"


def test_parse_stats_api_requires_cookie_and_updates_after_v1(hermes_root):
    reset_parse_stats()
    set_fake_engine({"mode": "tools", "calls": [{"name": "memory", "arguments": {"action": "add"}}]})
    try:
        client = TestClient(create_app(load_settings()))
        assert client.get("/api/parse-stats").status_code == 401
        assert client.post("/api/login", json={"username": "admin", "password": "admin"}).status_code == 200
        empty = client.get("/api/parse-stats")
        assert empty.status_code == 200
        assert empty.json()["counts"]["fence_ok"] == 0
        chat = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "messages": [{"role": "user", "content": "记住我叫测试"}],
                "tools": [{"type": "function", "function": {"name": "memory", "parameters": {"type": "object"}}}],
            },
        )
        assert chat.status_code == 200
        stats = client.get("/api/parse-stats").json()
        assert stats["counts"]["fence_ok"] == 1
        assert stats["last"]["kind"] == "tool_calls"
        assert "memory" in stats["last"]["tools"]
    finally:
        set_fake_engine(None)
        reset_parse_stats()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend\.venv\Scripts\python -m pytest tests\test_parse_stats.py tests\test_translator.py::test_parse_unknown_tool_name_degrades_to_text -q --tb=short`

Expected: FAIL (`degraded` missing and `/api/parse-stats` 404).

- [ ] **Step 3: Write minimal implementation**

1. `ParseResult` 增加 `degraded: bool = False`。未知工具名、围栏 JSON 无效、`calls` 滤空时 `degraded=True`。`tool_choice=none` 与普通句子为 `False`。
2. `stats.py` 进程内计数 + preview 截断 160。
3. `openai.py` 在 `parse_output` 后调用 `record_parse(parsed)`（成功路径；引擎失败不记解析）。
4. `settings_routes.py` 增加 `GET /api/parse-stats`。

- [ ] **Step 4: Run test to verify it passes**

Run: `backend\.venv\Scripts\python -m pytest tests\test_parse_stats.py tests\test_translator.py tests\test_parse_priority.py tests\test_gateway.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

Skip unless the user asks.

---

### Task 3: 收紧「记住」类 prompt

**Files:**
- Modify: `backend/tests/test_translator.py`
- Modify: `backend/app/translator/prompt.py`

**Interfaces:**
- Consumes: `build_prompt(messages, tools, tool_choice)`
- Produces: 输出契约里明确：记忆类指令必须用 `## Available tools` 里的**原名**；示例围栏仍用 `memory`，并写明 arguments 的 key 抄 schema，禁止自造工具名。

- [ ] **Step 1: Write the failing test**

```python
def test_build_prompt_tells_model_to_use_catalog_names_for_memory():
    text = build_prompt(
        messages=[{"role": "user", "content": "记住我叫张三"}],
        tools=TOOLS,
        tool_choice="auto",
    )
    assert "Available tools" in text
    assert "不要自己发明工具名" in text or "Do not invent tool names" in text
    assert "记住" in text or "remember" in text.lower()
```

用中文或英文其中一组固定下来，实现与测试同一句。推荐固定中文：`不要自己发明工具名`，并含 `若用户要求记住`。

- [ ] **Step 2: Run test to verify it fails**

Run: `backend\.venv\Scripts\python -m pytest tests\test_translator.py::test_build_prompt_tells_model_to_use_catalog_names_for_memory -q --tb=short`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

在 `_output_rules` 契约末尾追加两句：用户要求记住事实且 catalog 有记忆类工具时只出围栏；`name` 必须来自 catalog。

- [ ] **Step 4: Run test to verify it passes**

Run: `backend\.venv\Scripts\python -m pytest tests\test_translator.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

Skip unless the user asks.

---

### Task 4: 设置页展示解析计数

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/styles.css`
- Test: 浏览器打开 `http://127.0.0.1:5176` 设置页（开发）核对卡片

**Interfaces:**
- Consumes: `GET /api/parse-stats`（与 Task 2 相同 JSON）
- Produces: 设置页「最近一次解析」卡片：三项计数 + 最近 kind 标签 + 工具名

- [ ] **Step 1: Write the failing test**

无独立前端单测。验收：卡片标题为 `最近一次解析`，空态文案 `还没有 /v1 解析记录`。

- [ ] **Step 2: Run test to verify it fails**

打开设置页，当前没有该卡片。

- [ ] **Step 3: Write minimal implementation**

`api.ts` 增加 `ParseStats` 类型。`Settings.tsx` 在 `loadForm` 并行拉 `/api/parse-stats`；`loadQuota` 成功后也可刷新一次。卡片放在「当前主模型」和「运行」之间。`styles.css` 用现有 `.card` + 一个 `.stat-row`（三列数字）。

- [ ] **Step 4: Run test to verify it passes**

浏览器登录设置页，确认卡片与空态。用 TestClient 已覆盖 API。

- [ ] **Step 5: Commit**

Skip unless the user asks.

---

### Task 5: README 写成 P5 接入手册

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 规格 §15、§18；设置页 30 号字段
- Produces: 进度改为 P5；含启动、Hermes `hermes model` 选 30、`api_mode: chat_completions`、不要指辅助模型、第 18 节清单

- [ ] **Step 1: Write the failing test**

文档任务。核对 README 仍写「当前进度：P4」。

- [ ] **Step 2: Run test to verify it fails**

`README.md` 第一段是 P4。

- [ ] **Step 3: Write minimal implementation**

重写 README：启动、设置页登录、复制 30 号字段、`model: default`、辅助模型不要指过来、验收清单（1–7 必须，8 尽力）、流式说明（开展示流式不会加快本代理首字）。

- [ ] **Step 4: Run test to verify it passes**

通读 README，确认无真实密钥、进度为 P5。

- [ ] **Step 5: Commit**

Skip unless the user asks.

---

## Self-Review

1. Spec §18.1–7：1 已由 Hermes 打通覆盖；2/3/6/7 已有测试；4/5 由 Task 1 补文案；8 由 Task 2–4 落地计数与 prompt。
2. 不做：真增量 SSE、嵌套 Agent、Qoder 连接池、视觉。
3. 名称一致：`public_parse_stats` / `reset_parse_stats` / `record_parse` / `ParseResult.degraded`。
