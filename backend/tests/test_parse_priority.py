from app.translator.parse import parse_output

NAMES = ["memory", "skill_view"]


def test_tool_choice_none_ignores_fence():
    raw = """```hermes-proxy
{"type":"tool_calls","calls":[{"name":"memory","arguments":{}}]}
```"""
    out = parse_output(raw, tool_names=NAMES, tool_choice="none")
    assert out.kind == "text"
    assert "memory" in out.text


def test_fence_type_text_uses_content():
    raw = """```hermes-proxy
{"type":"text","content":"plain answer"}
```"""
    out = parse_output(raw, tool_names=NAMES, tool_choice="auto")
    assert out.kind == "text"
    assert out.text == "plain answer"


def test_whole_json_calls_array():
    out = parse_output(
        '{"calls":[{"name":"memory","arguments":{"k":1}}]}',
        tool_names=NAMES,
        tool_choice="auto",
    )
    assert out.kind == "tool_calls"
    assert out.calls[0]["name"] == "memory"


def test_whole_json_tool_calls_key():
    out = parse_output(
        '{"tool_calls":[{"name":"skill_view","arguments":"{\\"id\\":\\"x\\"}"}]}',
        tool_names=NAMES,
        tool_choice="auto",
    )
    assert out.kind == "tool_calls"
    assert out.calls[0]["name"] == "skill_view"


def test_whole_json_type_text():
    out = parse_output('{"type":"text","content":"hi"}', tool_names=NAMES, tool_choice="auto")
    assert out.kind == "text"
    assert out.text == "hi"


def test_plain_text_fallback():
    out = parse_output("just a sentence", tool_names=NAMES, tool_choice="auto")
    assert out.kind == "text"
    assert out.text == "just a sentence"


def test_named_tool_choice_filters_and_may_degrade():
    raw = """```hermes-proxy
{"type":"tool_calls","calls":[{"name":"skill_view","arguments":{}}]}
```"""
    out = parse_output(raw, tool_names=NAMES, tool_choice="memory")
    assert out.kind == "text"
    assert "skill_view" in out.text
