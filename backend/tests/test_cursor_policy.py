from app.adapters.cursor.policy import DISALLOWED_TOOLS, cursor_run_policy


def test_cursor_run_policy_disables_engine_tools():
    policy = cursor_run_policy()
    assert policy["tools"] == []
    assert policy["resume"] is None
    assert policy["setting_sources"] == []
    for name in ("shell", "edit", "read", "grep", "glob", "ls", "webSearch", "task", "delete", "applyAgentDiff"):
        assert name in DISALLOWED_TOOLS
        assert name in policy["disallowed_tools"]
    assert "applyPatch" not in DISALLOWED_TOOLS
