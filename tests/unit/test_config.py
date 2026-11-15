import pytest

from scheduler.config import DEFAULT_DATABASE_URL, get_settings, normalize_database_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgresql://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("sqlite://", "sqlite://"),
    ],
)
def test_normalize_database_url(raw: str, expected: str) -> None:
    assert normalize_database_url(raw) == expected


def test_defaults() -> None:
    settings = get_settings({})
    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.max_time_limit_s == 60.0


def test_environment_overrides() -> None:
    settings = get_settings({"DATABASE_URL": "postgres://a/b", "MAX_TIME_LIMIT_S": "5.5"})
    assert settings.database_url == "postgresql+psycopg://a/b"
    assert settings.max_time_limit_s == 5.5


def test_frontend_dir_setting() -> None:
    assert get_settings({"FRONTEND_DIR": "/srv/ui"}).frontend_dir == "/srv/ui"
    assert get_settings({"FRONTEND_DIR": ""}).frontend_dir is None
    default = get_settings({}).frontend_dir
    assert default is None or default.endswith("frontend")
