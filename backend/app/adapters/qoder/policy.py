from __future__ import annotations

from typing import Any

DENY_MESSAGE = "This proxy is the Hermes main model. Do not use engine tools."

DISALLOWED_TOOLS = (
    "Read",
    "Grep",
    "Glob",
    "LS",
    "Bash",
    "Edit",
    "Write",
    "Skill",
    "WebFetch",
    "WebSearch",
)


def qoder_run_policy(max_turns: int = 2) -> dict[str, Any]:
    return {
        "allowed_tools": [],
        "disallowed_tools": list(DISALLOWED_TOOLS),
        "resume": None,
        "max_turns": max_turns,
        "skills": [],
        "deny_message": DENY_MESSAGE,
    }


def deny_engine_tool(tool_name: str, tool_input: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"allow": False, "message": DENY_MESSAGE}
