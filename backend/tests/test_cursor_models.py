from app.config import load_settings
from app.models import list_public_models, normalize_cursor_model


def test_normalize_cursor_model_maps_cli_variants():
    assert normalize_cursor_model("cursor-grok-4.6-high") == "grok-4.6"
    assert normalize_cursor_model("cursor-grok-4.6-high-fast") == "grok-4.6"
    assert normalize_cursor_model("grok-4.6") == "grok-4.6"
    assert normalize_cursor_model("composer-2.5-fast") == "composer-2.5"
    assert normalize_cursor_model("claude-opus-5-thinking-high") == "claude-opus-5"
    assert normalize_cursor_model("auto") == "grok-4.6"
    assert normalize_cursor_model("") == "grok-4.6"
    assert normalize_cursor_model("brand-new-model") == "brand-new-model"


def test_list_public_models_includes_cursor_catalog(hermes_root):
    ids = [item["id"] for item in list_public_models(load_settings())]
    assert "cursor/grok-4.6" in ids
    assert "cursor/claude-opus-5" in ids
    assert "cursor/composer-2.5" in ids
