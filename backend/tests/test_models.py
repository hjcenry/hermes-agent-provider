import pytest

from app.config import load_settings
from app.models import parse_model, public_id


def test_parse_default_and_aliases(hermes_root):
    settings = load_settings()
    assert parse_model("", settings) == ("qoder", "qmodel_38max")
    assert parse_model("default", settings) == ("qoder", "qmodel_38max")
    assert parse_model("auto", settings) == ("qoder", "qmodel_38max")
    assert parse_model("qoder", settings) == ("qoder", "qmodel_38max")
    assert parse_model("cursor", settings) == ("cursor", "grok-4.6")
    assert parse_model("cursor/grok-4.6", settings) == ("cursor", "grok-4.6")
    assert parse_model("composer-2.5", settings) == ("qoder", "composer-2.5")


def test_parse_illegal_prefix(hermes_root):
    settings = load_settings()
    with pytest.raises(ValueError, match="qoder|cursor|default"):
        parse_model("openai/gpt-4", settings)


def test_public_id():
    assert public_id("qoder", "qmodel_38max") == "qoder/qmodel_38max"
