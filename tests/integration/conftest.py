"""Integration test setup.

These tests need a PostgreSQL database: set ``TEST_DATABASE_URL`` (CI does). Without it they are
skipped, and without SQLAlchemy installed they are not collected at all.
"""

import os
from collections.abc import Iterator

import pytest

try:
    import sqlalchemy  # noqa: F401
except ImportError:  # pragma: no cover - only when the project is not installed
    collect_ignore_glob = ["test_*.py"]
else:
    from sqlalchemy import Engine, create_engine
    from sqlalchemy.orm import Session

    from scheduler.db import models  # noqa: F401
    from scheduler.db.base import Base

    TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

    @pytest.fixture(scope="session")
    def engine() -> Iterator[Engine]:
        if not TEST_DATABASE_URL:
            pytest.skip("TEST_DATABASE_URL is not set")
        eng = create_engine(TEST_DATABASE_URL)
        Base.metadata.drop_all(eng)
        Base.metadata.create_all(eng)
        yield eng
        Base.metadata.drop_all(eng)
        eng.dispose()

    @pytest.fixture
    def session(engine: Engine) -> Iterator[Session]:
        """A session inside a transaction that is rolled back after each test."""
        connection = engine.connect()
        transaction = connection.begin()
        db = Session(connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
        try:
            yield db
        finally:
            db.close()
            transaction.rollback()
            connection.close()
