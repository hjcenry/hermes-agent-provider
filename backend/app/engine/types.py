from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EngineResult:
    ok: bool
    text: str = ""
    error: str | None = None
    error_class: str | None = None
    engine: str = ""
    model: str = ""
    session_id: str = ""
