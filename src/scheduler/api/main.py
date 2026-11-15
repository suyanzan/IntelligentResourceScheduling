"""Application factory. Run with ``uvicorn scheduler.api.main:app``."""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from scheduler import __version__
from scheduler.api.errors import register_error_handlers
from scheduler.api.routers import data, runs, scenarios
from scheduler.config import Settings, get_settings


def create_app(
    session_factory: sessionmaker[Session] | None = None, settings: Settings | None = None
) -> FastAPI:
    app = FastAPI(
        title="Intelligent Resource Scheduling Platform",
        version=__version__,
        description="CP-SAT based scheduling on fully synthetic data (independent project).",
    )
    app.state.session_factory = session_factory  # created lazily on first request when None
    app.state.settings = settings or get_settings()

    register_error_handlers(app)
    app.include_router(scenarios.router)
    app.include_router(runs.router)
    app.include_router(data.router)

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
