"""The app serves the dashboard at "/" without shadowing the API."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from scheduler.api.main import create_app  # noqa: E402
from scheduler.config import Settings, default_frontend_dir  # noqa: E402


def _client(frontend_dir: str | None) -> TestClient:
    settings = Settings(database_url="postgresql+psycopg://x/x", max_time_limit_s=5.0,
                        frontend_dir=frontend_dir)
    return TestClient(create_app(settings=settings))


def test_dashboard_and_assets_are_served() -> None:
    client = _client(default_frontend_dir())
    page = client.get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "Resource scheduling" in page.text
    assert client.get("/js/main.js").status_code == 200
    assert client.get("/css/styles.css").status_code == 200
    assert len(client.get("/vendor/d3.v7.9.0.min.js").content) > 100_000


def test_api_routes_win_over_static_files() -> None:
    client = _client(default_frontend_dir())
    assert client.get("/api/health").json()["status"] == "ok"
    missing = client.get("/api/does-not-exist")
    assert missing.status_code == 404
    assert "text/html" not in missing.headers["content-type"]


def test_api_only_mode() -> None:
    client = _client(None)
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200
