from __future__ import annotations

from typing import Any

from app.config import Settings

_ENGINES = {"qoder", "cursor"}
CURSOR_DEFAULT = "grok-4.6"
_CURSOR_CATALOG: tuple[tuple[str, str], ...] = (
    ("grok-4.6", "Grok 4.6"),
    ("composer-2.5", "Composer 2.5"),
    ("composer-2", "Composer 2"),
    ("grok-4.5", "Grok 4.5"),
    ("gpt-5.6-sol", "GPT-5.6 Sol"),
    ("gpt-5.6-terra", "GPT-5.6 Terra"),
    ("gpt-5.6-luna", "GPT-5.6 Luna"),
    ("gpt-5.5", "GPT-5.5"),
    ("gpt-5.4", "GPT-5.4"),
    ("gpt-5.4-mini", "GPT-5.4 Mini"),
    ("gpt-5.4-nano", "GPT-5.4 Nano"),
    ("gpt-5.3-codex", "GPT-5.3 Codex"),
    ("gpt-5.2", "GPT-5.2"),
    ("gpt-5.1", "GPT-5.1"),
    ("gpt-5-mini", "GPT-5 Mini"),
    ("claude-opus-5", "Claude Opus 5"),
    ("claude-opus-4-8", "Claude Opus 4.8"),
    ("claude-opus-4-7", "Claude Opus 4.7"),
    ("claude-opus-4-6", "Claude Opus 4.6"),
    ("claude-opus-4-5", "Claude Opus 4.5"),
    ("claude-sonnet-5", "Claude Sonnet 5"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ("claude-sonnet-4-5", "Claude Sonnet 4.5"),
    ("claude-sonnet-4", "Claude Sonnet 4"),
    ("claude-haiku-4-5", "Claude Haiku 4.5"),
    ("claude-fable-5-1", "Claude Fable 5.1"),
    ("claude-fable-5", "Claude Fable 5"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash"),
    ("gemini-3.7-flash", "Gemini 3.7 Flash"),
    ("gemini-3.6-flash", "Gemini 3.6 Flash"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash"),
    ("gemini-3.1-pro", "Gemini 3.1 Pro"),
    ("gemini-3-flash", "Gemini 3 Flash"),
    ("gemini-2.5-flash", "Gemini 2.5 Flash"),
    ("muse-spark-1.3", "Muse Spark 1.3"),
    ("kimi-k3", "Kimi K3"),
    ("kimi-k2.7-code", "Kimi K2.7 Code"),
    ("glm-5.2", "GLM 5.2"),
    ("default", "Auto"),
)


def normalize_cursor_model(raw: str | None) -> str:
    text = (raw or "").strip()
    ids = [item[0] for item in _CURSOR_CATALOG]
    if not text or text.lower() in {"auto", "default"}:
        try:
            from app.config import get_settings

            return get_settings().default_engine_model("cursor") or CURSOR_DEFAULT
        except Exception:
            return CURSOR_DEFAULT
    lowered = {item.lower(): item for item in ids}
    if text.lower() in lowered:
        return lowered[text.lower()]
    compact = text.lower()
    if compact.startswith("cursor-"):
        compact = compact[7:]
    for sid in sorted(ids, key=len, reverse=True):
        name = sid.lower()
        if compact == name or compact.startswith(f"{name}-"):
            return sid
    return text


def parse_model(raw: str | None, settings: Settings) -> tuple[str, str]:
    text = (raw or "").strip()
    if not text or text.lower() in {"default", "auto"}:
        engine = settings.default_engine()
        return engine, settings.default_engine_model(engine)
    if "/" in text:
        engine, _, model = text.partition("/")
        engine = engine.strip().lower()
        if engine not in _ENGINES:
            raise ValueError("引擎只能是 qoder、cursor 或 default")
        mid = model.strip()
        if not mid:
            return engine, settings.default_engine_model(engine)
        return engine, mid
    key = text.lower()
    if key in _ENGINES:
        return key, settings.default_engine_model(key)
    return settings.default_engine(), text


def public_id(engine: str, model: str) -> str:
    return f"{engine}/{model}"


def list_engine_models(engine: str, settings: Settings) -> dict[str, Any]:
    name = (engine or "").strip().lower() or settings.default_engine()
    if name not in _ENGINES:
        raise ValueError("引擎只能是 qoder 或 cursor")
    if name == "cursor":
        items = [{"id": mid, "label": label} for mid, label in _CURSOR_CATALOG]
    else:
        chosen = settings.default_engine_model("qoder")
        items = [{"id": chosen, "label": chosen}]
        for extra in ("qmodel_38max",):
            if extra != chosen:
                items.append({"id": extra, "label": extra})
    return {
        "engine": name,
        "default": settings.default_engine_model(name),
        "items": items,
    }


def list_public_models(settings: Settings) -> list[dict[str, Any]]:
    qoder = settings.default_engine_model("qoder")
    cursor = settings.default_engine_model("cursor")
    items = [
        _entry("default", "hermes-agent-provider"),
        _entry("qoder", "hermes-agent-provider"),
        _entry("cursor", "hermes-agent-provider"),
        _entry(public_id("qoder", qoder), "qoder"),
        _entry(public_id("cursor", cursor), "cursor"),
    ]
    seen = {item["id"] for item in items}
    for mid, _label in _CURSOR_CATALOG:
        key = public_id("cursor", mid)
        if key not in seen:
            items.append(_entry(key, "cursor"))
            seen.add(key)
    return items


def _entry(model_id: str, owned_by: str) -> dict[str, Any]:
    return {"id": model_id, "object": "model", "owned_by": owned_by}
