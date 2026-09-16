# hermes-agent-provider — 技术设计文档

> 版本：1.0.0  
> 状态：待评审  
> 日期：2026-09-16  
> 形态：**独立进程 / 独立仓库**，不改 Hermes 源码  
> 仓库名：`hermes-agent-provider`  
> 参考：已有 Cursor / Qoder 适配与额度展示思路  
> 读者：程序（落地）、使用者（Hermes 怎么配）

本文锁定第一期产品：本地代理对 Hermes 表现为 **custom provider 主模型**；脑力只来自本机已登录的 **Qoder** 或 **Cursor**。没有第三方 LLM Key。

---

## 目录

- [1. 背景与目标](#1-背景与目标)
- [2. 范围与非目标](#2-范围与非目标)
- [3. 核心结论](#3-核心结论)
- [4. 系统架构](#4-系统架构)
- [5. 主模型协议](#5-主模型协议)
- [6. 协议翻译](#6-协议翻译)
- [7. 引擎适配](#7-引擎适配)
- [8. 模型命名与路由](#8-模型命名与路由)
- [9. 设置页与额度](#9-设置页与额度)
- [10. 配置与密钥](#10-配置与密钥)
- [11. 鉴权、绑定与安全](#11-鉴权绑定与安全)
- [12. 并发、超时与错误](#12-并发超时与错误)
- [13. 工程结构](#13-工程结构)
- [14. 接口一览](#14-接口一览)
- [15. Hermes 接入](#15-hermes-接入)
- [16. 测试](#16-测试)
- [17. 分阶段交付](#17-分阶段交付)
- [18. 验收标准](#18-验收标准)
- [19. 明确取舍](#19-明确取舍)

---

## 1. 背景与目标

Hermes Agent 官方不支持 Cursor CLI，也没有 Qoder provider。Hermes 主模型只认 HTTP：`GET /v1/models` 与 `POST /v1/chat/completions`（`api_mode: chat_completions`）。

本机只有 Qoder / Cursor 账号，没有 OpenAI / OpenRouter 等主模型 Key。`cursor-sdk` 与 `qoder-agent-sdk` 是 Agent 运行时，不是 OpenAI 兼容网关。

目标：

1. 单独起一个代理服务，作为 Hermes 的 **custom provider 主模型源**。
2. 代理对内调用 Qoder 或 Cursor，对外说 OpenAI chat completions。
3. 提供设置页：选引擎、选模型、看账号额度、复制 Hermes 配置。
4. Hermes 继续当编排器：skill、memory、MCP 由 Hermes 执行，不由 Cursor/Qoder 执行。

成功标准：在 Hermes 里把主模型指到本代理后，能正常对话；当模型按约定回工具调用时，Hermes 会执行自己的 `memory` / `skill_view` / `skill_manage` 等工具并进入下一轮。

---

## 2. 范围与非目标

### 2.1 第一期要做

| 项 | 说明 |
|----|------|
| 独立仓库 | 只放代理与设置页，不拷排查助手业务 |
| OpenAI 门面 | `/v1/models`、`/v1/chat/completions`（JSON 与 SSE） |
| 主模型模式 | 关掉引擎自己的工具，只借模型和额度 |
| 双引擎 | Qoder、Cursor，设置页切换，请求里的 `model` 可覆盖 |
| 协议翻译 | messages / tools → 单次 prompt；引擎文本 → `content` 或 `tool_calls` |
| 设置页 | 引擎、模型、额度、登录态、Hermes 配置片段 |
| 本机默认 | 监听 `127.0.0.1:8765`，与排查助手 `8010` / `5175` 错开 |

### 2.2 明确不做

- 不把工单、飞书、SSH、Groovy、GM、CSV、词库带进本仓库。
- 不改 Hermes 源码，不写 Hermes 进程内 `create_client()` 插件。
- 第一期不做「整轮转给 Cursor/Qoder、让它们自己读文件改代码」的嵌套 Agent 模式。
- 不实现 ACP、不实现 Anthropic / Codex / Bedrock 原生协议。
- 不提供公开的裸 LLM。Cursor / Qoder 没有 completions API，本服务用 prompt 约束冒充 function calling。
- 不把引擎工具（Read / Grep / Shell / Edit）暴露给 Hermes。
- 不默认监听 `0.0.0.0`。
- 不做多租户、不做云端部署方案。

### 2.3 参考与不照搬

**借鉴** 现有引擎适配实现：

- `adapters/cursor/account.py`、`adapters/qoder/account.py` 的额度与登录态
- `engine/models.py` 的模型目录与默认值
- `engine/select.py` 的引擎名规范化
- `adapters/*/runner.py` 的 SDK 启动、Windows `ProactorEventLoop`、流式事件收集
- 前端额度卡片与引擎切换的交互，而不是整页工作台

**不照搬**：任务状态机、澄清/排查 prompt、技能文件、护栏白名单（本服务是「全禁引擎工具」，不是「只读白名单」）。

---

## 3. 核心结论

### 3.1 谁跑循环

| 角色 | 职责 |
|------|------|
| Hermes | 主编排。拼 system（人设、MEMORY 快照、skill 目录），带 `tools`，执行 `tool_calls`，写记忆、读 skill、跑 MCP |
| 本代理 | 主模型门面。把一轮补全翻译成一次引擎调用，把输出译回 OpenAI 格式 |
| Qoder / Cursor | 只当脑。禁止使用自己的工具。根据 Hermes 给的对话和工具 schema，决定回文本还是回 Hermes 工具名 |

### 3.2 为何可以没有「真主模型」

Hermes 不检查对方是不是 OpenAI。它只要求：

- 能列出模型
- 能收 `messages` + `tools`
- 能回 `message.content` 或 `message.tool_calls`

代理满足这三项，就**是**主模型。Qoder/Cursor 提供推理；代理提供契约。

### 3.3 与直连真 LLM 的差距（接受并写明）

引擎没有原生 function calling。代理用输出约定 + 解析来补。因此：

- 格式不稳时，该轮会变成纯文本，Hermes 工具循环少转一圈
- 一次调用的时延和计费按「一次 Agent 回合」，不是按一次真补全
- 必须硬禁引擎工具，否则两套 Agent 抢活，skill/memory 仍不会走 Hermes

第一期接受这些上限，用解析容错和 `max_turns` 限制把稳定性做够用，不追求 100% 对齐 Claude/GPT。

---

## 4. 系统架构

### 4.1 进程与端口

一个后端进程（FastAPI + uvicorn），开发时再加一个前端进程（Vite）。

| 进程 | 地址 | 作用 |
|------|------|------|
| 后端 | `127.0.0.1:8765` | `/v1/*` 给 Hermes；`/api/*` 给设置页；生产环境托管前端静态文件 |
| 前端（仅开发） | `127.0.0.1:5176` | 设置页，把 `/api`、`/v1` 代理到 `8765` |

后端 **不加** `--reload`。改 Python 后关掉进程再开（与排查助手相同，避免 Windows 上 SDK 子进程残留）。

```text
Hermes CLI / Gateway
        │  Authorization: Bearer <proxy_api_key>
        │  POST /v1/chat/completions
        ▼
hermes-agent-provider 后端 :8765
        │
        ├─ gateway     OpenAI 门面、鉴权、排队
        ├─ translator  messages/tools ↔ prompt ↔ 回包
        ├─ engine      按路由选 Qoder 或 Cursor
        ├─ settings    引擎/模型/额度 API
        └─ store       local.yaml 读写
                │
                ├─ qoder-agent-sdk  （工具全禁）
                └─ cursor-sdk       （工具全禁）

浏览器 :5176（开发）或 :8765（生产）
        │  登录 Cookie
        ▼
设置页
```

### 4.2 模块边界

每个模块只做一件事，只通过明确数据结构往来。

| 模块 | 做什么 | 怎么用 | 依赖 |
|------|--------|--------|------|
| `gateway` | HTTP、鉴权、SSE、请求校验 | Hermes 与设置页的入口 | translator、engine、settings |
| `translator` | 拼 prompt、解析引擎输出、组 OpenAI 回包 | 纯函数，可单测 | 无 SDK |
| `engine` | 选引擎、调 SDK、归一事件、禁工具 | `run(prompt, engine, model) -> EngineResult` | cursor/qoder adapter |
| `adapters.cursor` / `adapters.qoder` | SDK 细节、登录探测 | 只被 engine 调 | cursor-sdk / qoder-agent-sdk |
| `account` | 额度、登录态缓存 | 设置页与错误友好化 | 各引擎官方用量接口 |
| `settings_io` | 读合并配置、写 `local.yaml` | 启动与设置页保存 | PyYAML |
| `models` | 虚拟模型列表、解析 `qoder/xxx` | `/v1/models` 与路由 | account / 静态目录 |

禁止：gateway 直接 `import cursor_sdk`；adapter 直接拼 OpenAI chunk；translator 启动 SDK。

### 4.3 数据流（一轮 Hermes 主循环）

```text
1. Hermes 组装 messages + tools
2. POST /v1/chat/completions
3. gateway 校验 API Key、解析 model、领取并发槽
4. translator.build_prompt(messages, tools, tool_choice)
5. engine.run(prompt, engine, model)     # 引擎工具已关
6. translator.parse_output(raw_text)     # text | tool_calls
7. gateway 写成 JSON 或 SSE
8. Hermes：
     - 若 tool_calls → 执行工具，把 role=tool 再 POST
     - 若 text → 本轮结束，必要时后台 memory/skill review
```

同一 Hermes 会话的下一跳是 **新的** `chat/completions`。代理 **不** `resume` 引擎会话：历史已在 `messages` 里。每次 `AsyncAgent.create` / `query(...)` 都是新会话，避免 Hermes 历史与引擎记忆叠两份。

### 4.4 工作目录

SDK 必须有 `cwd`。第一期：

- 默认 `data/workspace/`（仓库内，gitignore）
- 设置页可改 `paths.workspace`
- **不要** 默认指到 `~/.hermes`。引擎工具已关，但 SDK 仍可能写项目文件；与 Hermes 家目录隔离，避免误伤记忆文件
- Hermes 自己的 MEMORY.md、skills 仍由 Hermes 工具读写，与代理 cwd 无关

---

## 5. 主模型协议

只实现 Hermes custom provider 的 `chat_completions` 子集。多出来的 OpenAI 字段忽略，不报错。

### 5.1 `GET /v1/models`

请求头：`Authorization: Bearer <proxy_api_key>`。

响应：

```json
{
  "object": "list",
  "data": [
    {"id": "default", "object": "model", "owned_by": "hermes-agent-provider"},
    {"id": "qoder", "object": "model", "owned_by": "hermes-agent-provider"},
    {"id": "cursor", "object": "model", "owned_by": "hermes-agent-provider"},
    {"id": "qoder/qmodel_38max", "object": "model", "owned_by": "qoder"},
    {"id": "cursor/grok-4.6", "object": "model", "owned_by": "cursor"}
  ]
}
```

`data` 还包含该引擎当前能列到的全部模型（Qoder 走 SDK `get_available_models`，Cursor 走内置目录）。拉列表失败时仍返回 `default` / `qoder` / `cursor` 和配置里的默认模型，不 500。

### 5.2 `POST /v1/chat/completions`

读取的字段：

| 字段 | 行为 |
|------|------|
| `model` | 路由，见第 8 节。缺省当 `default` |
| `messages` | 必填，OpenAI 角色 |
| `tools` | 可选。有则写入 prompt，供模型决定 `tool_calls` |
| `tool_choice` | `auto`（默认）/`none`/`required` / 指定函数。变成 prompt 约束，不是 SDK 参数 |
| `stream` | `true` 时 SSE，见 5.4 |
| `temperature` 等 | 忽略，不向前传（SDK 不保证支持） |

不实现：`n>1`、`response_format`、视觉多模态、`functions` 旧字段（若只带 `functions` 当 `tools` 读）。

### 5.3 非流式响应

文本：

```json
{
  "id": "chatcmpl-<uuid>",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "qoder/qmodel_38max",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "……"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

工具调用：`content` 为 `null`，`finish_reason` 为 `tool_calls`，`tool_calls[].function.arguments` 必须是 **JSON 字符串**。`usage` 固定 0；引擎不提供可用 token 计数。

### 5.4 流式响应

`Content-Type: text/event-stream`。每行 `data: {json}`，最后 `data: [DONE]`。

第一期 **先收齐引擎输出再重放 SSE**，不边跑边推 content。原因：必须先看完整文本才能判断是 `tool_calls` 还是普通回复；中途推了 content 再改成 tool_calls，Hermes 会乱。

- 文本：先发带 `delta.role=assistant` 的 chunk，再按约 40 字符切 `delta.content`，最后 `finish_reason=stop`
- 工具：不发 content；发 `delta.tool_calls`（或 Hermes 能收的等价最终 chunk），`finish_reason=tool_calls`

客户端断开则取消引擎运行（SDK `cancel` / `aclose`）。

### 5.5 不实现的 Hermes 侧能力

- 不实现 `/v1/responses`、Anthropic messages
- 不把引擎 thinking 映射成 Hermes 的 reasoning 字段（第一期丢弃 thinking，避免污染 content）
- 不在 `/v1` 上做 Hermes gateway 的 `X-Hermes-Session-Token`；那是 Hermes 自己的管理面

---

## 6. 协议翻译

translator 是本系统最容易测、也最容易让 skill/memory 失效的部分。规则全部写死，不靠「模型自己看着办」。

### 6.1 `messages` → 正文

按数组顺序拼接，每条前加角色标签：

| role | 标签 |
|------|------|
| `system` | `## System` |
| `user` | `## User` |
| `assistant`（纯文本） | `## Assistant` |
| `assistant`（含 `tool_calls`） | `## Assistant tool_calls` + 每个 `name` 与 `arguments` |
| `tool` | `## Tool result` + `tool_call_id` + 正文 |

`content` 为数组时只拼 `type=text` 的 `text`。图片等直接写成 `[omitted non-text part]`，第一期不做视觉。

### 6.2 `tools` → 工具清单

在正文前加一节 `## Available tools`，把每个 function 的 `name`、`description`、`parameters` 以 JSON 原样列出。名称必须与 Hermes 传入的一致（`memory`、`skill_view`、`skill_manage` 等），**不得改名**。

### 6.3 输出约定（写入 prompt 末尾）

引擎看不到 OpenAI 的 `tool_calls` 字段，必须按下面约定输出。prompt 用中英各写一遍要点，避免模型跑偏。

**只允许两种最终输出（思考过程不要出现在最终输出里）：**

1. 纯文本：直接写给用户看的话，不要包 JSON，不要解释你在选工具。
2. 工具调用，且必须是下面围栏的 **唯一** 内容：

````text
```hermes-proxy
{"type":"tool_calls","calls":[{"name":"memory","arguments":{}}]}
```
````

`arguments` 必须是对象，对应 Hermes 该工具的 JSON Schema。需要多个工具就往 `calls` 里追加。

`tool_choice`：

- `none`：禁止围栏，只能纯文本
- `required` 或指定函数：必须出围栏；指定函数时 `name` 必须是那个函数
- `auto`：按需二选一

并写明：

- 不要使用 Cursor/Qoder 自己的 Read、Grep、Shell、Edit、终端
- 要读文件、改记忆、加载 skill，只能用 `## Available tools` 里的名字
- 不要把围栏和用户可见正文混在同一条回复里

### 6.4 解析优先级

对引擎最终 `answer` 做：

1. 去掉首尾空白。
2. `tool_choice=none`：无论有没有围栏，整段当文本。
3. 若存在 \`\`\`hermes-proxy 围栏，解析围栏内 JSON；`type=tool_calls` 且 `calls` 非空 → 工具调用；`type=text` → 用其 `content`。
4. 否则若 **整段** 是 JSON，且含 `tool_calls` 或 `calls` 数组 → 工具调用。
5. 否则若整段是 JSON 且 `type=text` → 文本。
6. 否则整段当文本。若文本里夹着未闭合围栏或明显半截 JSON，仍当文本，不猜测。

`tool_choice` 为指定函数时：解析出的 `calls` 只保留该 `name`；一个都不剩则降级为文本。

工具调用规范化：

- 每个 call 生成 `id`：`call_` + 12 位 hex
- `name` 必须落在本轮 `tools` 里；否则整单降级为文本（把原始输出放进 content，让 Hermes 当普通话看，避免虚构工具名打崩循环）
- `arguments` 对象 → `json.dumps` 成字符串；若已是字符串则校验能 `json.loads`，失败则该 call 丢掉，若一个都不剩则降级为文本

### 6.5 构建 OpenAI `tool_calls`

```json
{
  "id": "call_ab12cd34ef56",
  "type": "function",
  "function": {
    "name": "memory",
    "arguments": "{\"action\":\"add\",\"content\":\"...\"}"
  }
}
```

Hermes 下一轮会带 `role=tool` 的结果。translator 按 6.1 再拼进去，引擎在新会话里看到完整因果。

---

## 7. 引擎适配

### 7.1 统一结果

```text
EngineResult
  ok: bool
  text: str           # 最终助手文本（已去掉 thinking）
  error: str | None
  error_class: login | quota | timeout | cancelled | engine | unknown
  engine: qoder | cursor
  model: str
  session_id: str     # 仅日志，不用于 resume
```

adapter 把 SDK 事件收成 `text`。`thinking` / `status` / 引擎自己的 `tool` 事件 **不进入** `text`。若引擎仍打出自己的工具调用，只记日志，当没看见。

### 7.2 主模型模式：关掉引擎工具

这是 skill/memory 能走 Hermes 的前提。

**Cursor**（`cursor_sdk.AgentOptions`）：

- `tools=[]`
- `disallowed_tools` 至少包括：`shell`、`edit`、`read`、`grep`、`glob`、`ls`、`webSearch`、`task`、`delete`、`applyPatch`，以及排查助手里用过的全部短名
- 不传项目 skill，不设 `setting_sources` 去加载会恢复工具的规则；`setting_sources=[]`
- 每次 `AsyncAgent.create`，不 `resume`

**Qoder**（`QoderAgentOptions`）：

- `allowed_tools=[]`
- `disallowed_tools` 使用静态表：`Read`、`Grep`、`Glob`、`LS`、`Bash`、`Edit`、`Write`、`Skill`、`WebFetch`、`WebSearch`。此表只是提示 SDK，**不是**安全边界。
- `can_use_tool` **恒拒绝**（含未知工具名），返回：`This proxy is the Hermes main model. Do not use engine tools.`
- `skills` 传空：有 `skills=` 参数则传空列表 / 关闭值；没有该参数则只靠 `can_use_tool`。不加载本仓库或项目里的 skill 文件。
- `max_turns=2`：即使漏网一次工具拒绝，还有一回合吐最终答案
- 每次新 `query()`，`resume=None`

若某版本 SDK 忽略空 `tools`，以 `can_use_tool` / `disallowed_tools` 为准，并在设置页「引擎诊断」里显示最近一次是否出现引擎侧 tool 事件（只计数，不展示路径内容）。

### 7.3 调用方式（与参考仓库对齐）

**Cursor**：`AsyncClient.launch_bridge(workspace=cwd)` → `AsyncAgent.create` → `agent.send(prompt)` → 读 `stream()` → `run.wait()`。Windows 上在专用线程里开 `WindowsProactorEventLoopPolicy`。API Key：`CURSOR_API_KEY` 或 `~/.cursor/sdk/auth.json`。

**Qoder**：`query(prompt=..., options=...)`。Auth：`QODER_PERSONAL_ACCESS_TOKEN` / `QODERCN_PERSONAL_ACCESS_TOKEN` 或本机 `qodercli`。同样需要 Windows Proactor。

模型 ID 在交给 SDK 前去掉 `qoder/`、`cursor/` 前缀，并走与排查助手相同的 `normalize_cursor_model`。

### 7.4 登录与额度（设置页，不挡第一句也可调）

复用排查助手的探测逻辑：

- Cursor：`usage-summary` + 本机 session / API Key
- Qoder：`QoderSDKClient.get_usage_info()`

缓存 TTL 90 秒。设置页「刷新」强制拉一次。  
`/v1/chat/completions` **不**因为额度 UI 还在 loading 就拒绝；只有引擎返回额度/鉴权错误时才 429/401。

友好错误文案从 account 模块出，与排查助手同一套判断（quota / auth / network），但去掉「对齐理解 / 工单」用词。

---

## 8. 模型命名与路由

### 8.1 解析规则

对 `model` 字符串 `strip` 后：

| 输入 | 引擎 | 引擎侧模型 |
|------|------|------------|
| 空 / `default` / `auto` | 设置页当前引擎 | 该引擎在设置里的默认模型 |
| `qoder` | qoder | 设置里的 qoder 默认模型 |
| `cursor` | cursor | 设置里的 cursor 默认模型 |
| `qoder/<id>` | qoder | `<id>` |
| `cursor/<id>` | cursor | `<id>` |
| 其它（无前缀） | 设置页当前引擎 | 原字符串（交给该引擎规范化） |

非法引擎名（例如 `openai/gpt-4`）→ `400`，说明只支持 `qoder` / `cursor` / `default`。

### 8.2 默认值

与排查助手起步值一致，可在 `local.yaml` 改：

- 默认引擎：`qoder`
- Qoder 默认模型：`qmodel_38max`
- Cursor 默认模型：`grok-4.6`

设置页保存后立刻影响 `default` / `qoder` / `cursor` 三个别名，不影响已经写死的 `qoder/其它id`。

### 8.3 Hermes 怎么选

推荐 Hermes `model.default` 写成 `default` 或 `qoder/qmodel_38max`。换引擎以设置页为准时用 `default`；希望 Hermes `/model` 自己切换时用带前缀的 id（`/v1/models` 已列出）。

---

## 9. 设置页与额度

设置页是给 **人** 用的，不是给 Hermes 用的。Hermes 只打 `/v1`。

### 9.1 页面结构（单页，无工单）

1. **当前主模型**  
   引擎单选：Qoder / Cursor。  
   该引擎模型下拉（数据来自 `/api/engines/models`）。  
   展示 Hermes 将用到的完整 id，例如 `qoder/qmodel_38max`。
2. **额度**  
   两张卡片（Qoder、Cursor），复用排查助手的套餐 / 加量 / 百分比展示。  
   登录态、刷新按钮、额度用尽提示。
3. **连接**  
   只读：监听地址、`base_url`（`http://127.0.0.1:8765/v1`）。  
   可复制的 Hermes `config.yaml` 片段（含当前 default 与「把 api_key 换成你的 proxy key」）。  
   工作目录输入框。
4. **运行**  
   最大并发、引擎超时秒数。保存写 `local.yaml` 并热加载。

不做：YAML 大编辑器、技能编辑、服务器列表。

### 9.2 设置页 API

`/api/*` **只接受 Cookie**（见第 11 节）。Hermes 的 Bearer 不能读、也不能改这些接口，避免对话或日志里的 Key 被拿来改配置。排障看设置页或后端日志。

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/me` | 当前登录用户 |
| POST | `/api/login` | 用户名密码 |
| POST | `/api/logout` | 退出 |
| GET | `/api/engines/status` | 双引擎额度与登录态、当前 active |
| PUT | `/api/engines/active` | 切换默认引擎 |
| GET | `/api/engines/models` | 某引擎模型列表 |
| GET | `/api/settings` | 可编辑项（引擎默认模型、cwd、并发、超时） |
| PUT | `/api/settings` | 保存到 `local.yaml` 并 reload |
| GET | `/api/hermes-snippet` | 生成当前 Hermes 配置文本 |

切换引擎与改默认模型立即生效，无需重启，正在跑的请求仍用它们开始时解析好的引擎/模型。

### 9.3 前端形态

React + Vite，端口 `5176`，视觉从排查助手收一档（侧栏额度 + 中间表单），去掉任务导航。生产构建输出到 `backend/app/static`，由 FastAPI 挂在 `/`。

---

## 10. 配置与密钥

三层合并，后者覆盖前者：`config/default.yaml` ← `config/local.yaml` ← `config/secrets.env`。

`default.yaml` 入库。`local.yaml`、`secrets.env` 不入库，只给 example。

### 10.1 `default.yaml` 形状

```yaml
server:
  host: 127.0.0.1
  port: 8765

engines:
  default: qoder          # qoder | cursor
  models:
    qoder: qmodel_38max
    cursor: grok-4.6

runtime:
  max_concurrency: 2
  timeout_sec: 180
  max_turns: 2            # 引擎内部回合，不是 Hermes 循环

paths:
  workspace: data/workspace

auth:
  users:
    - { username: admin, role: admin }
```

### 10.2 `secrets.env` 键

| 键 | 用途 |
|----|------|
| `PROXY_API_KEY` | Hermes 调 `/v1` 的 Bearer。未配置则启动失败（开发可在 example 里放本地随机串，正式自己换） |
| `SETTINGS_PASSWORD` | 设置页 `admin` 的密码 |
| `SESSION_SECRET` | Cookie 签名 |
| `CURSOR_API_KEY` | 可选，也可用本机 SDK 登录 |
| `QODER_PERSONAL_ACCESS_TOKEN` / `QODERCN_PERSONAL_ACCESS_TOKEN` | 可选，也可用 qodercli |

不在日志、不在 `/api/hermes-snippet` 里回传完整 Key；snippet 用 `YOUR_PROXY_API_KEY` 占位，设置页对已配置的 Key 只显示后 4 位。

### 10.3 热加载

保存设置后 `get_settings(reload=True)`。改 `secrets.env` 仍须重启（与排查助手相同）。改端口/host 须重启，设置页写明。

---

## 11. 鉴权、绑定与安全

### 11.1 两条入口

| 入口 | 鉴权 | 调用方 |
|------|------|--------|
| `/v1/*` | `Authorization: Bearer` 等于 `PROXY_API_KEY` | Hermes |
| `/api/*`（除 login） | 签名 Cookie | 浏览器设置页 |
| `/` 静态页 | 未登录只显示登录框 | 人 |

Key 比较用恒定时间比较。缺头或错误 → `401`，body 为 OpenAI 风格 `{"error":{"message":"...","type":"invalid_request_error"}}`，避免 Hermes 解析失败。

### 11.2 绑定

默认 `127.0.0.1`。配置成非回环地址不算第一期功能；若有人改了 host，文档警告：Bearer Key 即主模型权，等于能消耗 Qoder/Cursor 额度。

### 11.3 日志与落盘

- 默认只记：请求 id、引擎、模型、耗时、`finish_reason`、`error_class`、prompt/completion **字符长度**
- `runtime.log_prompts: false`（默认）。为 true 时写入 `data/logs/`，不入库
- 不把 `messages` 写入 sqlite，不落会话库
- 引擎 cwd 与 Hermes 家目录隔离（4.4）

### 11.4 工具面安全

代理不执行 Hermes 工具。Hermes 工具的风险仍是 Hermes 自己的策略（命令确认、memory write_approval 等）。本服务多做的只有：禁止引擎工具，降低「Composer 在代理 cwd 改文件」的概率。

---

## 12. 并发、超时与错误

### 12.1 排队

全局信号量，容量 = `runtime.max_concurrency`（默认 2）。槽满时等待，最多再等 `timeout_sec`；等不到 → `429`，`message` 说明代理忙。

Hermes 若把辅助模型也指到本代理（记忆回顾等），走同一队列。第一期不拆辅助通道。文档建议：辅助模型尽量不要指过来，避免回顾再烧一轮 Cursor。

### 12.2 超时

单次引擎调用硬超时 `runtime.timeout_sec`（默认 180）。超时取消 SDK 运行，返回 `504`，`error_class=timeout`。

### 12.3 HTTP 映射

| 情况 | HTTP | OpenAI `error.type` |
|------|------|---------------------|
| Key 错 / 缺 | 401 | `invalid_request_error` |
| `messages` 空、model 非法 | 400 | `invalid_request_error` |
| 排队满 | 429 | `rate_limit_error` |
| 引擎额度用尽 | 429 | `rate_limit_error` |
| 引擎未登录 / Key 失效 | 401 | `invalid_request_error` |
| 引擎超时 | 504 | `server_error` |
| 引擎崩溃 / 未知 | 502 | `server_error` |
| 客户端取消 | 不补发 body | — |

`stream=true` 时，若尚未发送第一个 chunk，用普通 JSON 错误；若已开始 SSE，发一个 `error` 字段 chunk 再 `[DONE]`，避免 Hermes 挂死。

---

## 13. 工程结构

```text
hermes-agent-provider/
  README.md
  .gitignore
  config/
    default.yaml
    local.yaml.example
    secrets.env.example
  docs/superpowers/specs/2026-09-16-hermes-proxy-design.md
  backend/
    requirements.txt
    app/
      main.py
      config.py
      auth.py
      gateway/openai.py
      translator/{prompt.py,parse.py,openai_out.py}
      engine/{dispatch.py,types.py}
      adapters/cursor/{runner.py,account.py}
      adapters/qoder/{runner.py,account.py}
      settings_io.py
      models.py
      api/settings_routes.py
    tests/
      test_translator.py
      test_models.py
      test_gateway.py
      test_engine_fake.py
  frontend/
    package.json
    src/{App.tsx,api.ts,pages/Login.tsx,pages/Settings.tsx,Quota.tsx}
  scripts/windows/{start-all.bat,start-backend.bat,start-frontend.bat}
  scripts/mac/{start-all.sh,start-backend.sh,start-frontend.sh}
  data/                    # gitignore：workspace、logs
```

Python 3.11+。依赖核心：`fastapi`、`uvicorn`、`pydantic`、`pyyaml`、`python-dotenv`、`itsdangerous`、`httpx`、`pytest`、`qoder-agent-sdk`、`cursor-sdk`。版本下限与排查助手对齐，便于同一台机器共用环境经验。

---

## 14. 接口一览

### 14.1 Hermes（Bearer）

- `GET /v1/models`
- `POST /v1/chat/completions`
- `GET /healthz`：无鉴权，返回 `{"ok":true}`，给启动脚本探活

### 14.2 设置页（Cookie）

见 9.2。`POST /api/login` body：`{"username","password"}`。第一期只允许 `auth.users` 里的账号。

### 14.3 跨域

开发时 Vite 与 `8765` 不同源：Vite 只代理，不配宽松 CORS。生产同源。Hermes 是服务端出站，无 CORS 问题。

---

## 15. Hermes 接入

使用者本机 `~/.hermes/config.yaml`（或 `hermes model` 向导向 custom endpoint）：

```yaml
model:
  default: default
  provider: custom
  base_url: http://127.0.0.1:8765/v1
  api_key: 与 PROXY_API_KEY 相同
  api_mode: chat_completions
  discover_models: true
```

步骤：

1. 本机登录 Qoder 或 Cursor（与排查助手相同）。
2. 启动代理，打开 `http://127.0.0.1:5176`（开发）或 `http://127.0.0.1:8765`，确认额度绿。
3. 写入上面的 Hermes 配置。
4. `hermes chat` 发一句；代理日志应出现一次 `finish_reason=stop` 或 `tool_calls`。
5. 若要换引擎：改设置页，Hermes 继续用 `default`；或 `/model cursor/grok-4.6`。

不提供 Hermes 官方插件包。custom provider 已够。

辅助模型：第一期建议保持 Hermes 默认（跟主模型走或关闭回顾），不在文档里引导把 vision/summarizer 指到本代理。

---

## 16. 测试

不测真实云端扣费。引擎用假适配器。

### 16.1 单测（必过）

| 文件 | 断言 |
|------|------|
| `test_translator.py` | 多角色 messages 拼接；tool 历史进 prompt；围栏 JSON → `tool_calls`；arguments 对象转字符串；未知工具名降级为文本；半截 JSON 当文本；`tool_choice=none` 时即使有围栏也当文本（translator 在 parse 前看 flag） |
| `test_models.py` | `default` / `qoder` / `cursor/grok-4.6` / 非法前缀 |
| `test_openai_out.py` | 非流式 JSON 形状；SSE 以 `[DONE]` 结束；tool_calls 的 arguments 为 str |
| `test_gateway.py` | 无 Bearer → 401；假引擎文本与工具调用各一条 httpx 测 FastAPI |
| `test_parse_priority.py` | 第 6.4 节每一级优先级各一例（含 `tool_choice=none`） |

### 16.2 假引擎

`engine.dispatch` 可注入：`{"mode":"text","text":"..."}` / `{"mode":"tools","calls":[...]}` / `{"mode":"error","class":"quota"}`。gateway 测试只走注入，不加载 SDK。

### 16.3 手工验收

1. `curl` `/healthz`、`/v1/models`、`/v1/chat/completions`（`stream=false/true`）。
2. 设置页切换引擎、刷新额度、复制 snippet。
3. 真 Hermes：一句闲聊；一句「记住我叫……」看是否出现 `memory` 的 `tool_calls`（允许偶发失败，见 18）。
4. 未登录引擎时，Hermes 应看到 401/可读错误，而不是空流。

---

## 17. 分阶段交付

只做这一份规格里的主模型代理，按阶段开工，不平行铺嵌套 Agent。

| 阶段 | 交付 | 完成定义 |
|------|------|----------|
| P0 | 仓库骨架、配置合并、`/healthz`、启动脚本 | 本机脚本能拉起后端 |
| P1 | translator + `/v1` 走假引擎 + 单测 | pytest 绿；curl 能拿到 stop / tool_calls |
| P2 | Qoder 真适配（工具全禁）+ 额度 API | 登录后 `GET /api/engines/status` 能返回 Qoder 额度；curl `/v1` 经 Qoder 出文本 |
| P3 | Cursor 真适配 + 模型目录 | `GET /api/engines/status` 含 Cursor；curl `model=cursor/grok-4.6` 可跑 |
| P4 | 设置页完整（引擎、模型、snippet、并发） | 浏览器改默认引擎后，下一次 `/v1` 走新引擎 |
| P5 | README 接入步骤 + 对 Hermes 手工走通 | 第 18 节清单打勾 |

P1 未绿之前不接真 SDK，避免协议与账单问题缠在一起。

---

## 18. 验收标准

**必须：**

1. Hermes 把 `base_url` 指到 `http://127.0.0.1:8765/v1` 后能完成至少一轮用户可见回复。
2. `/v1/models` 列出 `default`、`qoder`、`cursor` 及带前缀模型。
3. 设置页可切换 Qoder/Cursor，可改默认模型，能看到两侧额度或明确的未登录原因。
4. 引擎未登录时 `/v1` 返回 401，不空转。
5. 额度用尽时返回 429，文案能看懂。
6. 单测覆盖 translator 优先级与 OpenAI 回包形状。
7. 默认只听 `127.0.0.1`；无 Bearer 不能调 `/v1`。

**尽力（不因单次失败挡发布）：**

8. 在「记住这个事实」类指令下，代理至少能解析出一次 `memory`（或当前 Hermes 工具名）的 `tool_calls`。若连续三次手工都失败，记为已知限制，打开设置页「最近一次解析结果」计数（成功围栏 / 降级文本），再收紧 prompt，不因此改回嵌套 Agent。

---

## 19. 明确取舍

| 主题 | 决定 |
|------|------|
| 产品 | 独立代理，当 Hermes 主模型，不当排查助手 |
| 循环归属 | Hermes 编排；引擎只生成 |
| 引擎工具 | 第一期全关；嵌套 Agent 以后若做必须另开模式，默认不准 |
| 会话 | 不 resume 引擎；历史只走 Hermes `messages` |
| 流式 | 先收齐再重放 SSE |
| 端口 | `8765` / 开发 UI `5176` |
| 鉴权 | `/v1` 用 Bearer；设置页用 Cookie |
| token 用量 | 回 0，不估 |
| 辅助模型 | 不引导指到本代理 |
| 视觉 | 不做 |
| 与排查助手 | 只抄适配与额度思路，不共用进程、不共用数据库 |

---

## 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0.0 | 2026-09-16 | 初稿。来源：对话 17239ba7（requestId 62f43981）及本仓库需求对齐 |
