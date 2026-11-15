"""Comparing runs through the HTTP API. Needs OR-Tools as well as PostgreSQL."""

from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("ortools")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scheduler.api.deps import get_session  # noqa: E402
from scheduler.api.main import create_app  # noqa: E402
from scheduler.config import Settings  # noqa: E402


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app(settings=Settings(database_url="unused", max_time_limit_s=30.0))
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client


def two_jobs(resources: list[str], *, window_end: int = 24, horizon: int = 24) -> dict[str, Any]:
    """Two 4-unit jobs that are both due at 4: on time only if they can run in parallel."""
    return {
        "horizon": horizon,
        "resources": [
            {"id": rid, "name": f"Line {rid}", "windows": [{"start": 0, "end": window_end}]}
            for rid in resources
        ],
        "jobs": [
            {"id": "J1", "name": "Order 1", "duration": 4, "due": 4, "eligible": resources},
            {"id": "J2", "name": "Order 2", "duration": 4, "due": 4, "eligible": resources},
        ],
    }


def scenario(client: TestClient, name: str, instance: dict[str, Any]) -> int:
    response = client.post("/api/scenarios", json={"name": name, "instance": instance})
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def solve(client: TestClient, scenario_id: int, **body: Any) -> dict[str, Any]:
    response = client.post(
        f"/api/scenarios/{scenario_id}/solve", json={"time_limit_s": 20, **body}
    )
    assert response.status_code == 201, response.text
    run: dict[str, Any] = response.json()
    return run


def compare(client: TestClient, run_a: int, run_b: int) -> Any:
    return client.get("/api/compare", params={"run_a": run_a, "run_b": run_b})


def test_same_scenario_same_settings_is_a_tie(client: TestClient) -> None:
    sid = scenario(client, "s", two_jobs(["R1"]))
    a, b = solve(client, sid), solve(client, sid)
    body = compare(client, a["id"], b["id"]).json()
    assert body["same_scenario"] and body["same_inputs"] and body["objective_comparable"]
    assert body["better"] == "tie"
    assert body["metrics"]["objective"]["change"] == 0
    assert body["a"]["id"] == a["id"] and body["b"]["id"] == b["id"]
    assert body["moved_jobs"] == sum(1 for job in body["jobs"] if job["moved"])
    assert [job["job_id"] for job in body["jobs"]] == ["J1", "J2"]


def test_different_objective_kinds_are_not_ranked(client: TestClient) -> None:
    sid = scenario(client, "s", two_jobs(["R1"]))
    body = compare(
        client, solve(client, sid, weighted=True)["id"], solve(client, sid, weighted=False)["id"]
    ).json()
    assert body["same_inputs"] and not body["objective_comparable"]
    assert body["better"] is None
    assert any("different objectives" in note for note in body["notes"])


def test_what_if_extra_line_across_scenarios(client: TestClient) -> None:
    base = solve(client, scenario(client, "one line", two_jobs(["R1"])))
    more = solve(client, scenario(client, "two lines", two_jobs(["R1", "R2"])))
    assert base["metrics"]["total_tardiness"] == 4 and more["metrics"]["total_tardiness"] == 0

    body = compare(client, base["id"], more["id"]).json()
    assert not body["same_scenario"] and not body["same_inputs"]
    assert body["better"] is None  # different inputs: no winner is named
    assert any("different inputs" in note for note in body["notes"])
    assert body["metrics"]["total_tardiness"] == {"a": 4.0, "b": 0.0, "change": -4.0}
    assert body["metrics"]["on_time_rate"]["change"] == pytest.approx(0.5)
    assert set(body["utilization"]) == {"R1", "R2"}
    assert body["utilization"]["R2"]["a"] is None  # the extra line did not exist before
    assert body["utilization"]["R2"]["b"] is not None
    by_job = {job["job_id"]: job for job in body["jobs"]}
    assert sum(job["tardiness_change"] for job in by_job.values()) == -4


def test_run_without_a_schedule(client: TestClient) -> None:
    infeasible = scenario(client, "tight", two_jobs(["R1"], window_end=5, horizon=5))
    bad = solve(client, infeasible)
    assert bad["status"] == "INFEASIBLE"
    good = solve(client, scenario(client, "ok", two_jobs(["R1"])))

    body = compare(client, bad["id"], good["id"]).json()
    assert body["better"] is None
    assert body["metrics"]["total_tardiness"]["a"] is None
    assert body["metrics"]["total_tardiness"]["change"] is None
    assert any("Run A has no schedule (INFEASIBLE)" in note for note in body["notes"])
    assert all(job["a"] is None for job in body["jobs"])


def test_unknown_run_and_bad_parameters(client: TestClient) -> None:
    sid = scenario(client, "s", two_jobs(["R1"]))
    run = solve(client, sid)
    missing = compare(client, run["id"], 999_999)
    assert missing.status_code == 404
    assert "999999" in missing.json()["detail"]
    assert compare(client, 0, run["id"]).status_code == 422
    assert client.get("/api/compare", params={"run_a": run["id"]}).status_code == 422
