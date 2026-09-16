from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.settings_routes import router as settings_router
from app.config import Settings, get_settings
from app.gateway.openai import router as openai_router


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    cfg.require_proxy_api_key()
    application = FastAPI(title="hermes-agent-provider", version="0.1.0")
    application.state.settings = cfg
    application.add_middleware(
        SessionMiddleware,
        secret_key=cfg.session_secret(),
        same_site="lax",
        https_only=False,
    )
    application.include_router(settings_router)
    application.include_router(openai_router)

    @application.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    static_dir = Path(__file__).resolve().parent / "static"
    if (static_dir / "index.html").is_file():
        application.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")

    return application
