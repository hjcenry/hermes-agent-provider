from __future__ import annotations

from typing import Any

# Cursor SDK 只接受当前 ToolName；旧名 applyPatch 会直接 502。
# tools=[] 已表示不提供内置工具；这份名单是同名再挡一层。
DISALLOWED_TOOLS = (
    "shell",
    "edit",
    "read",
    "grep",
    "glob",
    "ls",
    "webSearch",
    "webFetch",
    "task",
    "mcp",
    "delete",
    "readLints",
    "semSearch",
    "updateTodos",
    "readTodos",
    "askQuestion",
    "await",
    "generateImage",
    "applyAgentDiff",
)


def cursor_run_policy() -> dict[str, Any]:
    return {
        "tools": [],
        "disallowed_tools": list(DISALLOWED_TOOLS),
        "resume": None,
        "setting_sources": [],
    }
