"""Application settings read from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATABASE_URL = "postgresql+psycopg://scheduler:scheduler@localhost:5432/scheduler"
DEFAULT_MAX_TIME_LIMIT_S = 60.0


def normalize_database_url(url: str) -> str:
    """Point plain ``postgres://`` / ``postgresql://`` URLs (as hosting providers hand them out)
    at the psycopg 3 driver that this project uses."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def default_frontend_dir() -> str | None:
    """The ``frontend`` folder next to ``src`` when running from a source checkout."""
    candidate = Path(__file__).resolve().parents[2] / "frontend"
    return str(candidate) if (candidate / "index.html").is_file() else None


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    max_time_limit_s: float
    frontend_dir: str | None = None  # served at "/" when set; None serves the API only
    # Local time of the plant as a fixed offset from UTC in minutes (480 = UTC+8, no DST). Plan
    # dates ("today") and the planned times shown to the floor use it.
    plan_utc_offset_minutes: int = 480


def get_settings(env: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env
    return Settings(
        database_url=normalize_database_url(source.get("DATABASE_URL", DEFAULT_DATABASE_URL)),
        max_time_limit_s=float(source.get("MAX_TIME_LIMIT_S", DEFAULT_MAX_TIME_LIMIT_S)),
        frontend_dir=(source["FRONTEND_DIR"] or None)
        if "FRONTEND_DIR" in source
        else default_frontend_dir(),
        plan_utc_offset_minutes=int(source.get("PLAN_UTC_OFFSET_MINUTES", 480)),
    )
