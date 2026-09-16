import json

from app.translator.openai_out import completion_payload, iter_sse


def test_text_completion_shape():
    body = completion_payload(
        model="qoder/qmodel_38max",
        text="hello",
        calls=None,
        completion_id="chatcmpl-x",
        created=1710000000,
    )
    assert body["id"] == "chatcmpl-x"
    assert body["object"] == "chat.completion"
    assert body["model"] == "qoder/qmodel_38max"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"] == "hello"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def test_tool_calls_arguments_are_str():
    body = completion_payload(
        model="qoder/qmodel_38max",
        text=None,
        calls=[{"id": "call_ab12cd34ef56", "name": "memory", "arguments": '{"action":"add"}'}],
        completion_id="chatcmpl-y",
        created=1,
    )
    message = body["choices"][0]["message"]
    assert message["content"] is None
    assert body["choices"][0]["finish_reason"] == "tool_calls"
    assert message["tool_calls"][0]["type"] == "function"
    assert isinstance(message["tool_calls"][0]["function"]["arguments"], str)
    assert json.loads(message["tool_calls"][0]["function"]["arguments"])["action"] == "add"


def test_sse_text_ends_with_done_and_has_role_chunk():
    body = completion_payload(
        model="qoder/qmodel_38max",
        text="hello",
        calls=None,
        completion_id="chatcmpl-z",
        created=1,
    )
    events = list(iter_sse(body))
    assert events[-1] == "data: [DONE]\n\n"
    first = json.loads(events[0][6:])
    assert first["choices"][0]["delta"]["role"] == "assistant"
    joined = "".join(
        json.loads(item[6:])["choices"][0]["delta"].get("content") or ""
        for item in events
        if item.startswith("data: {")
    )
    assert joined == "hello"


def test_sse_tool_calls_has_no_content_delta():
    body = completion_payload(
        model="cursor/grok-4.6",
        text=None,
        calls=[{"id": "call_1", "name": "memory", "arguments": "{}"}],
        completion_id="chatcmpl-t",
        created=1,
    )
    events = list(iter_sse(body))
    assert events[-1] == "data: [DONE]\n\n"
    payloads = [json.loads(item[6:]) for item in events if item.startswith("data: {")]
    assert any(item["choices"][0]["delta"].get("tool_calls") for item in payloads)
    assert all(item["choices"][0]["delta"].get("content") in (None, "", missing) or True for item, missing in ((p, object()) for p in payloads))
    contents = [item["choices"][0]["delta"].get("content") for item in payloads]
    assert not any(contents)
    assert payloads[-1]["choices"][0]["finish_reason"] == "tool_calls"
