"""Alembic environment. The URL is ``sqlalchemy.url`` if set, otherwise ``DATABASE_URL``."""

from alembic import context
from sqlalchemy import create_engine, pool

from scheduler.config import get_settings, normalize_database_url
from scheduler.db import models  # noqa: F401  (registers all tables on the metadata)
from scheduler.db.base import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    return normalize_database_url(configured) if configured else get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
