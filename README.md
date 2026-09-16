# hermes-agent-provider

给 [Hermes Agent](https://hermes-agent.nousresearch.com/) 接本机引擎的本地供应器。

现在内置 **Cursor**、**Qoder**，以后还能加别的引擎。不需要 OpenAI 或其他云厂商的 LLM Key：脑力来自你已经登录的 Cursor / Qoder 账号额度。

Hermes 把它当成 **custom provider**。接线协议是 Hermes 要求的 Chat Completions 门面（`/v1/models`、`/v1/chat/completions`），**不是** OpenAI 官方服务，下层也不是 OpenAI，而是各引擎自己的 SDK。

A local provider for Hermes Agent. It turns your signed-in Cursor or Qoder account into the main model. No third-party LLM API key.

## 它做什么

| 角色 | 职责 |
|------|------|
| Hermes Agent | 编排对话、技能、记忆、MCP，执行 `tool_calls` |
| 本仓库 | 把一轮补全翻译成一次引擎调用，再译回 Hermes 能认的回包 |
| Cursor / Qoder | 只当推理引擎。本服务会关掉它们自己的读文件、改代码等工具 |

一句话：Hermes 当主编排，本机引擎当脑。

## 要求

- Python 3.11+（后端）
- Node 18+（设置页开发时）
- 本机已登录 **Cursor** 或 **Qoder**（SDK / CLI / 在设置页粘贴 token）
- 已安装 [Hermes Agent](https://hermes-agent.nousresearch.com/)

## 启动

首次运行会把 `config/secrets.env.example` 复制为 `config/secrets.env`。请立刻改掉 `PROXY_API_KEY`，这就是 Hermes 要填的 API key。不要把 `secrets.env` 提交到 git。

Windows：

```text
scripts\windows\start-backend.bat
scripts\windows\start-frontend.bat
```

macOS：

```text
chmod +x scripts/mac/start-backend.sh scripts/mac/start-frontend.sh
scripts/mac/start-backend.sh
scripts/mac/start-frontend.sh
```

- 后端：`http://127.0.0.1:8765`，探活 `/healthz`
- 设置页：`http://127.0.0.1:5176`，默认账号 `admin` / `SETTINGS_PASSWORD`
- 只监听 `127.0.0.1`。`/v1` 用 Bearer，设置页用 Cookie

不要给 uvicorn 加 `--reload`。改 Python 后关掉进程再开。引擎令牌可在设置页「加载并生效」，不必重启。

生产可 `cd frontend && npm run build`，静态文件由后端挂在 `/`。

## 接入 Hermes

1. 本机登录 Cursor 或 Qoder。设置页两侧额度应可读，或能看到明确的未登录原因。
2. 终端执行 `hermes model`，选 **30. Custom endpoint (enter URL manually)**，粘贴：
   - URL：`http://127.0.0.1:8765/v1`
   - API key：`PROXY_API_KEY`
   - Model：`default`（走设置页当前引擎；也可写 `cursor/grok-4.6`、`qoder/qmodel_38max`）
   - API 兼容模式：**2 Chat Completions**（`api_mode: chat_completions`）
3. 或写入 `~/.hermes/config.yaml`：

```yaml
model:
  default: default
  provider: custom
  base_url: http://127.0.0.1:8765/v1
  api_key: 与 PROXY_API_KEY 相同
  api_mode: chat_completions
  discover_models: true
```

4. 发一句闲聊。换引擎：改设置页后 Hermes 继续用 `model: default`，或 `/model cursor/grok-4.6`。

不要把 vision / summarizer 等辅助模型指到本服务，回顾会再烧一轮引擎额度。

## 行为说明

- 引擎工具第一期全关，避免和 Hermes 抢着改文件。
- 不 resume 引擎会话；历史只走 Hermes 的 `messages`。
- `stream=true` 时先收齐引擎输出，再重放 SSE。必须先看完整文本才能判断是普通回复还是 Hermes `tool_calls`。Hermes 里打开展示流式，不会加快首字。
- 闲聊觉得慢：换更快的引擎模型，或降低 Hermes 的 `reasoning_effort`。
- 设置页「最近一次解析」统计围栏成功 / 纯文本 / 降级，方便看记忆、技能有没有被认成工具。

## 测试

```text
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
```

不测真实云端扣费。本地假引擎可用环境变量 `HERMES_AGENT_PROVIDER_FAKE`。

## 配置

三层合并，后者覆盖前者：`config/default.yaml` ← `config/local.yaml` ← `config/secrets.env`。

| 项 | 说明 |
|----|------|
| `PROXY_API_KEY` | Hermes 调用 `/v1` 的 Bearer |
| `SETTINGS_PASSWORD` | 设置页密码 |
| `CURSOR_API_KEY` | 可选，也可本机 Cursor SDK 登录 |
| `QODER_PERSONAL_ACCESS_TOKEN` | 可选，也可本机 `qodercli` 登录 |

设计文档：[docs/superpowers/specs/2026-09-16-hermes-proxy-design.md](docs/superpowers/specs/2026-09-16-hermes-proxy-design.md)

## 安全

- 默认不监听 `0.0.0.0`。谁拿到 `PROXY_API_KEY`，谁就能消耗你的 Cursor / Qoder 额度。
- `config/secrets.env` 已在 `.gitignore` 中，请勿提交。
- 本服务不执行 Hermes 的工具；命令确认、记忆写入仍由 Hermes 自己的策略负责。
