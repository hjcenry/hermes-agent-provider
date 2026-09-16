from app.adapters.qoder.policy import DISALLOWED_TOOLS, deny_engine_tool, qoder_run_policy


def test_qoder_run_policy_disables_engine_tools():
    policy = qoder_run_policy(max_turns=2)
    assert policy["allowed_tools"] == []
    assert policy["resume"] is None
    assert policy["max_turns"] == 2
    assert policy["skills"] == []
    for name in ("Read", "Grep", "Bash", "Edit", "Write", "Skill"):
        assert name in DISALLOWED_TOOLS
        assert name in policy["disallowed_tools"]


def test_deny_engine_tool_always_denies():
    result = deny_engine_tool("Read", {"path": "x"})
    assert result["allow"] is False
    assert "Hermes main model" in result["message"]
    assert deny_engine_tool("UnknownTool", {})["allow"] is False
