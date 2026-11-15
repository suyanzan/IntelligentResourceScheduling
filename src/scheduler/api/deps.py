"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from scheduler.config import Settings
from scheduler.db.session import make_engine, make_session_factory


def get_session(request: Request) -> Iterator[Session]:
    """One session per request. Write endpoints commit explicitly; anything uncommitted is rolled
    back when the session closes. The engine is created on first use."""
    factory = request.app.state.session_factory
    if factory is None:
        factory = make_session_factory(make_engine(request.app.state.settings.database_url))
        request.app.state.session_factory = factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
