"""The static frontend is self-consistent: every file the page refers to exists."""

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def test_index_references_exist() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="([^"#]+)"', html)
    assert refs, "index.html should reference scripts and styles"
    for ref in refs:
        assert not ref.startswith(("http:", "https:", "//")), f"{ref}: use vendored files only"
        assert (FRONTEND / ref).is_file(), f"index.html refers to missing file {ref}"


def test_module_imports_resolve() -> None:
    for script in (FRONTEND / "js").glob("*.js"):
        for target in re.findall(r'from\s+"(\.[^"]+)"', script.read_text(encoding="utf-8")):
            assert (script.parent / target).is_file(), f"{script.name} imports missing {target}"


def test_d3_is_vendored_with_its_license() -> None:
    assert (FRONTEND / "vendor" / "d3.v7.9.0.min.js").stat().st_size > 100_000
    assert "Copyright" in (FRONTEND / "vendor" / "d3.LICENSE.txt").read_text(encoding="utf-8")
