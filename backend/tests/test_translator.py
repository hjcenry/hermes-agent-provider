from app.translator.prompt import build_prompt
from app.translator.parse import parse_output

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory",
            "description": "store a fact",
            "parameters": {"type": "object", "properties": {"action": {"type": "string"}}},
        },
    }
]


def test_build_prompt_joins_roles_in_order():
    text = build_prompt(
        messages=[
            {"role": "system", "content": "you are hermes"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
        tools=None,
        tool_choice="auto",
    )
    assert text.index("## System") < text.index("you are hermes") < text.index("## User")
    assert "## Assistant" in text
    assert "hello" in text
    assert "```hermes-proxy" in text


def test_build_prompt_includes_tool_history_and_schema():
    text = build_prompt(
        messages=[
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "memory", "arguments": '{"action":"add"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "saved"},
        ],
        tools=TOOLS,
        tool_choice="auto",
    )
    assert "## Assistant tool_calls" in text
    assert "memory" in text
    assert "## Tool result" in text
    assert "call_1" in text
    assert "saved" in text
    assert "## Available tools" in text
    assert '"name": "memory"' in text or '"name":"memory"' in text


def test_build_prompt_flattens_text_parts_and_omits_images():
    text = build_prompt(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "see this"},
                    {"type": "image_url", "image_url": {"url": "x"}},
                ],
            }
        ],
        tools=None,
        tool_choice="none",
    )
    assert "see this" in text
    assert "[omitted non-text part]" in text


def test_build_prompt_tells_model_to_use_catalog_names_for_memory():
    text = build_prompt(
        messages=[{"role": "user", "content": "记住我叫张三"}],
        tools=TOOLS,
        tool_choice="auto",
    )
    assert "Available tools" in text
    assert "不要自己发明工具名" in text
    assert "若用户要求记住" in text


def test_parse_fence_tool_calls_stringifies_arguments():
    raw = """```hermes-proxy
{"type":"tool_calls","calls":[{"name":"memory","arguments":{"action":"add"}}]}
```"""
    out = parse_output(raw, tool_names=["memory"], tool_choice="auto")
    assert out.kind == "tool_calls"
    assert out.calls[0]["name"] == "memory"
    assert out.calls[0]["id"].startswith("call_")
    assert out.calls[0]["arguments"] == '{"action": "add"}' or '"action"' in out.calls[0]["arguments"]
    import json

    assert json.loads(out.calls[0]["arguments"])["action"] == "add"


def test_parse_unknown_tool_name_degrades_to_text():
    raw = """```hermes-proxy
{"type":"tool_calls","calls":[{"name":"not_a_tool","arguments":{}}]}
```"""
    out = parse_output(raw, tool_names=["memory"], tool_choice="auto")
    assert out.kind == "text"
    assert out.degraded is True
    assert "not_a_tool" in out.text


def test_parse_partial_json_is_text():
    out = parse_output('{"type":"tool_calls"', tool_names=["memory"], tool_choice="auto")
    assert out.kind == "text"
    assert out.degraded is False
    assert out.text.startswith('{"type":"tool_calls"')
