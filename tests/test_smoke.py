"""Phase 0 smoke tests: the package imports and the engine stays framework-free."""

import importlib
import sys

import scheduler


def test_package_version() -> None:
    assert scheduler.__version__ == "0.1.0"


def test_layers_importable() -> None:
    for name in ("engine", "db", "services", "api", "synthetic"):
        importlib.import_module(f"scheduler.{name}")


def test_engine_has_no_web_or_db_imports() -> None:
    forbidden = ("fastapi", "sqlalchemy", "pydantic")
    for mod in [m for m in sys.modules if m.startswith("scheduler.engine")]:
        module = sys.modules[mod]
        for attr in vars(module).values():
            root = getattr(attr, "__module__", "") or ""
            assert not root.startswith(forbidden)
