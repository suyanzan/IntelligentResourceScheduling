"""Solving through the HTTP API. Needs OR-Tools as well as PostgreSQL."""

import datetime as dt
from collections import defaultdict
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


def tiny(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/data/generate", json={"preset": "tiny"})
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


def solve(client: TestClient, scenario_id: int, **body: Any) -> Any:
    return client.post(f"/api/scenarios/{scenario_id}/solve", json={"time_limit_s": 20, **body})


def test_solve_returns_a_verified_optimal_run(client: TestClient) -> None:
    scenario = tiny(client)
    response = solve(client, scenario["id"])
    assert response.status_code == 201, response.text
    run = response.json()

    assert run["status"] == "OPTIMAL"
    assert run["gap"] == 0
    assert run["messages"] == []
    assert run["scenario_id"] == scenario["id"]
    assert run["input_hash"] and run["solver_version"]
    assert len(run["assignments"]) == scenario["job_count"]
    assert run["metrics"]["total_tardiness"] == sum(a["tardiness"] for a in run["assignments"])

    jobs = {j["id"]: j for j in scenario["instance"]["jobs"]}
    windows = {r["id"]: r["windows"] for r in scenario["instance"]["resources"]}
    by_resource: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in run["assignments"]:
        job = jobs[a["job_id"]]
        assert a["resource_id"] in job["eligible"]
        assert a["end"] - a["start"] == job["duration"]
        assert a["tardiness"] == max(0, a["end"] - job["due"])
        assert any(
            w["start"] <= a["start"] and a["end"] <= w["end"] for w in windows[a["resource_id"]]
        )
        by_resource[a["resource_id"]].append(a)
    for items in by_resource.values():
        items.sort(key=lambda a: a["start"])
        assert all(prev["end"] <= cur["start"] for prev, cur in zip(items, items[1:], strict=False))


def test_assignments_carry_calendar_datetimes(client: TestClient) -> None:
    scenario = tiny(client)
    run = solve(client, scenario["id"]).json()
    origin = dt.datetime(2026, 1, 5)
    for a in run["assignments"]:
        assert dt.datetime.fromisoformat(a["start_at"]) == origin + dt.timedelta(hours=a["start"])
        assert dt.datetime.fromisoformat(a["end_at"]) == origin + dt.timedelta(hours=a["end"])


def test_runs_are_listed_and_fetchable(client: TestClient) -> None:
    scenario = tiny(client)
    first = solve(client, scenario["id"]).json()
    second = solve(client, scenario["id"], weighted=False).json()
    assert second["weighted"] is False

    listed = client.get(f"/api/scenarios/{scenario['id']}/runs").json()
    assert [r["id"] for r in listed] == [second["id"], first["id"]]
    assert "assignments" not in listed[0]
    assert client.get(f"/api/scenarios/{scenario['id']}").json()["run_count"] == 2

    fetched = client.get(f"/api/runs/{first['id']}").json()
    assert fetched["assignments"] == first["assignments"]


def test_infeasible_is_a_successful_request_with_a_clear_status(client: TestClient) -> None:
    created = client.post(
        "/api/scenarios",
        json={
            "name": "Too much work",
            "instance": {
                "horizon": 5,
                "resources": [{"id": "R1", "name": "a", "windows": [{"start": 0, "end": 5}]}],
                "jobs": [
                    {"id": "A", "name": "a", "duration": 3, "due": 5, "eligible": ["R1"]},
                    {"id": "B", "name": "b", "duration": 3, "due": 5, "eligible": ["R1"]},
                ],
            },
        },
    ).json()
    response = solve(client, created["id"])
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "INFEASIBLE"
    assert run["assignments"] == [] and run["metrics"] is None
    assert run["objective_value"] is None
    assert any("infeasible" in m for m in run["messages"])


def test_time_limit_above_the_server_cap_is_rejected(client: TestClient) -> None:
    scenario = tiny(client)
    response = solve(client, scenario["id"], time_limit_s=31)
    assert response.status_code == 422
    assert "exceed" in response.json()["detail"]
    assert client.get(f"/api/scenarios/{scenario['id']}").json()["run_count"] == 0


@pytest.mark.parametrize("body", [{"time_limit_s": 0}, {"num_workers": 0}, {"random_seed": -1}])
def test_invalid_solve_parameters(client: TestClient, body: dict[str, Any]) -> None:
    scenario = tiny(client)
    assert solve(client, scenario["id"], **body).status_code == 422


def test_solving_with_defaults_needs_no_body(client: TestClient) -> None:
    scenario = tiny(client)
    response = client.post(f"/api/scenarios/{scenario['id']}/solve")
    assert response.status_code == 201
    assert response.json()["time_limit_s"] == 30.0


def test_runs_lock_inputs_but_clones_stay_editable(client: TestClient) -> None:
    scenario = tiny(client)
    solve(client, scenario["id"])

    instance = {k: scenario["instance"][k] for k in ("horizon", "resources", "jobs")}
    locked = client.put(f"/api/scenarios/{scenario['id']}/instance", json=instance)
    assert locked.status_code == 409
    assert "clone" in locked.json()["detail"]

    clone = client.post(f"/api/scenarios/{scenario['id']}/clone", json={"name": "Copy"}).json()
    assert clone["run_count"] == 0
    assert client.put(f"/api/scenarios/{clone['id']}/instance", json=instance).status_code == 200


def test_same_parameters_give_the_same_objective(client: TestClient) -> None:
    scenario = tiny(client)
    a = solve(client, scenario["id"]).json()
    b = solve(client, scenario["id"]).json()
    assert a["objective_value"] == b["objective_value"]
    assert a["input_hash"] == b["input_hash"]
