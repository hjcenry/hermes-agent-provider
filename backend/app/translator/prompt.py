from __future__ import annotations

import json
from typing import Any


def build_prompt(
    messages: list[dict[str, Any]] | None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str = "auto",
) -> str:
    parts: list[str] = []
    catalog = _tool_catalog(tools)
    if catalog:
        parts.append("## Available tools\n" + json.dumps(catalog, ensure_ascii=False, indent=2))
    for message in messages or []:
        if isinstance(message, dict):
            parts.append(_format_message(message))
    parts.append(_output_rules(tool_choice, bool(catalog)))
    return "\n\n".join(part for part in parts if part)


def _tool_catalog(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        items.append(
            {
                "name": name,
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {},
            }
        )
    return items


def _format_message(message: dict[str, Any]) -> str:
    role = str(message.get("role") or "").strip().lower()
    calls = message.get("tool_calls")
    if role == "assistant" and isinstance(calls, list) and calls:
        lines = ["## Assistant tool_calls"]
        for call in calls:
            fn = call.get("function") if isinstance(call, dict) and isinstance(call.get("function"), dict) else {}
            name = str(fn.get("name") or "")
            arguments = fn.get("arguments")
            lines.append(f"- {name}: {arguments}")
        return "\n".join(lines)
    if role == "tool":
        tool_id = str(message.get("tool_call_id") or "")
        return f"## Tool result\n{tool_id}\n{_content_text(message.get('content'))}"
    label = {"system": "## System", "user": "## User", "assistant": "## Assistant"}.get(role, f"## {role or 'Message'}")
    return f"{label}\n{_content_text(message.get('content'))}"


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                bits.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                bits.append(part)
            else:
                bits.append("[omitted non-text part]")
        return "\n".join(bits)
    return str(content)


def _output_rules(tool_choice: str, has_tools: bool) -> str:
    choice = (tool_choice or "auto").strip() or "auto"
    if choice == "none" or not has_tools:
        extra = (
            "tool_choice=none: 禁止围栏，只能纯文本 / output plain text only, no hermes-proxy fence."
            if choice == "none"
            else "No tools are available. Reply with plain text only."
        )
    elif choice == "required":
        extra = "tool_choice=required: 必须输出 hermes-proxy 围栏，calls 不能为空。"
    elif choice not in {"auto", "none", "required"}:
        extra = f'tool_choice 指定函数：calls 里只能有 name="{choice}"。'
    else:
        extra = "tool_choice=auto: 需要调用工具就出围栏，否则只回纯文本。"
    return f"""## Output contract

You are the Hermes main model. Do not use Cursor/Qoder Read, Grep, Shell, Edit, or terminal.
To read files, write memory, or load a skill, only use names in ## Available tools.
Do not mix a fence with user-visible prose.

只允许两种最终输出（思考过程不要出现在最终输出里）：
1. 纯文本：直接写给用户看的话，不要包 JSON，不要解释你在选工具。
2. 工具调用，且必须是下面围栏的唯一内容：

```hermes-proxy
{{"type":"tool_calls","calls":[{{"name":"memory","arguments":{{}}}}]}}
```

{extra}

若用户要求记住某个事实，且 ## Available tools 里有记忆类工具，只输出围栏，不要先用中文答应。
name 必须原样抄 catalog，arguments 的 key 抄该工具 parameters，不要自己发明工具名。
"""
