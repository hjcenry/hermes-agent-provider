from app.engine.dispatch import run_engine, set_fake_engine
from app.engine.types import EngineResult


def test_fake_text_result():
    set_fake_engine({"mode": "text", "text": "hello"})
    try:
        result = run_engine("prompt", engine="qoder", model="qmodel_38max")
        assert isinstance(result, EngineResult)
        assert result.ok is True
        assert result.text == "hello"
        assert result.engine == "qoder"
        assert result.model == "qmodel_38max"
    finally:
        set_fake_engine(None)


def test_fake_tools_result_is_parseable_fence():
    set_fake_engine({"mode": "tools", "calls": [{"name": "memory", "arguments": {"action": "add"}}]})
    try:
        result = run_engine("prompt", engine="cursor", model="grok-4.6")
        assert result.ok is True
        assert "```hermes-proxy" in result.text
        assert "memory" in result.text
    finally:
        set_fake_engine(None)


def test_fake_quota_error():
    set_fake_engine({"mode": "error", "class": "quota"})
    try:
        result = run_engine("prompt", engine="qoder", model="qmodel_38max")
        assert result.ok is False
        assert result.error_class == "quota"
    finally:
        set_fake_engine(None)
