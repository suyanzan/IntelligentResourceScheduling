"""Releasing a plan to the production floor and recording what really happened.

Needs OR-Tools (to solve a plan) and PostgreSQL.
"""

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("ortools")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scheduler.api.deps import get_session  # noqa: E402
from scheduler.api.main import create_app  # noqa: E402
from scheduler.config import Settings  # noqa: E402

TAIPEI = dt.timezone(dt.timedelta(hours=8))


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app(settings=Settings(database_url="unused", max_time_limit_s=30.0))
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client


def solved_run(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = client.post("/api/data/generate", json={"preset": "opc_live"}).json()
    run = client.post(
        f"/api/scenarios/{scenario['id']}/solve", json={"time_limit_s": 5, "no_idle": True}
    ).json()
    assert run["status"] in ("OPTIMAL", "FEASIBLE")
    return scenario, run


def release(client: TestClient, run_id: int, **extra: Any) -> dict[str, Any]:
    response = client.post("/api/floor/plans", json={"run_id": run_id, **extra})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def job(plan: dict[str, Any], job_id: str) -> dict[str, Any]:
    return next(j for j in plan["jobs"] if j["id"] == job_id)


def test_sample_data_starts_today_in_plant_time(client: TestClient) -> None:
    before = dt.datetime.now(TAIPEI)
    scenario, _ = solved_run(client)
    after = dt.datetime.now(TAIPEI)
    assert scenario["horizon_start"] in (before.date().isoformat(), after.date().isoformat())
    starts = {r["id"]: r["windows"][0]["start"] for r in scenario["instance"]["resources"]}
    assert set(starts.values()) == {0}  # every line is free from 00:00 today


def test_no_plan_until_one_is_released(client: TestClient) -> None:
    assert client.get("/api/floor/plan").status_code == 404
    assert client.post("/api/floor/plans", json={"run_id": 99999}).status_code == 404


def test_release_returns_the_plan_in_plant_time(client: TestClient) -> None:
    _, run = solved_run(client)
    plan = release(client, run["id"], released_by="Scheduler", note="first release")
    assert plan["active"] is True and plan["released_by"] == "Scheduler"
    assert plan["utc_offset_minutes"] == 480
    assert len(plan["jobs"]) == 40 and {line["id"] for line in plan["lines"]} == set("ABCDE")
    assert {j["status"] for j in plan["jobs"]} == {"planned"}
    for item in plan["jobs"]:
        assert item["due_at"].endswith("+08:00")
        assert item["planned_start_at"] < item["planned_end_at"]
    today = dt.datetime.now(TAIPEI).date()
    dues = {dt.datetime.fromisoformat(j["due_at"]).date() for j in plan["jobs"]}
    assert dues <= {today + dt.timedelta(days=n) for n in (1, 2, 3)}  # end of today/tomorrow/...
    assert client.get("/api/floor/plan").json()["id"] == plan["id"]


def test_start_complete_note_and_undo(client: TestClient) -> None:
    _, run = solved_run(client)
    plan = release(client, run["id"])
    code = plan["jobs"][0]["id"]
    base = f"/api/floor/plans/{plan['id']}/jobs/{code}"

    started = client.post(f"{base}/start", json={"by": "Mei", "note": "on line B"}).json()
    row = job(started, code)
    assert row["status"] == "running" and row["actual_start_at"] and row["updated_by"] == "Mei"
    assert row["note"] == "on line B" and row["actual_end_at"] is None

    finished = client.post(f"{base}/complete", json={"by": "Mei"}).json()
    row = job(finished, code)
    assert row["status"] == "done" and row["actual_end_at"] >= row["actual_start_at"]

    back = client.post(f"{base}/revert", json={"by": "Mei"}).json()
    assert job(back, code)["status"] == "running" and job(back, code)["actual_end_at"] is None
    back = client.post(f"{base}/revert", json={}).json()
    assert job(back, code)["status"] == "planned" and job(back, code)["actual_start_at"] is None

    noted = client.post(f"{base}/note", json={"note": "waiting for the mask", "by": "Lee"}).json()
    assert job(noted, code)["note"] == "waiting for the mask"

    events = client.get(f"/api/floor/plans/{plan['id']}/events").json()
    assert [e["action"] for e in events] == ["note", "revert", "revert", "complete", "start"]
    assert events[-1]["actor"] == "Mei" and events[-1]["job_id"] == code


def test_a_job_never_started_needs_a_start_time_to_complete(client: TestClient) -> None:
    _, run = solved_run(client)
    plan = release(client, run["id"])
    base = f"/api/floor/plans/{plan['id']}/jobs/{plan['jobs'][1]['id']}"
    refused = client.post(f"{base}/complete", json={})
    assert refused.status_code == 409 and "start time" in refused.json()["detail"]
    now = dt.datetime.now(dt.UTC)
    ok = client.post(
        f"{base}/complete",
        json={
            "started_at": (now - dt.timedelta(hours=2)).isoformat(),
            "at": (now - dt.timedelta(minutes=5)).isoformat(),
        },
    )
    assert ok.status_code == 200
    assert job(ok.json(), plan["jobs"][1]["id"])["status"] == "done"


def test_rule_violations_are_conflicts(client: TestClient) -> None:
    _, run = solved_run(client)
    plan = release(client, run["id"])
    code = plan["jobs"][0]["id"]
    base = f"/api/floor/plans/{plan['id']}/jobs/{code}"
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=3)).isoformat()
    assert client.post(f"{base}/start", json={"at": future}).status_code == 409
    assert client.post(f"{base}/start", json={}).status_code == 200
    assert client.post(f"{base}/start", json={}).status_code == 409  # already running
    naive = client.post(f"{base}/complete", json={"at": "2026-11-15T10:00:00"})
    assert naive.status_code == 422  # a time without a zone is refused by the schema
    assert client.post(f"{base}/revert", json={}).status_code == 200
    assert client.post(f"{base}/revert", json={}).status_code == 409  # nothing left to undo
    assert client.post(f"/api/floor/plans/{plan['id']}/jobs/NOPE/start", json={}).status_code == 404


def test_a_new_release_retires_the_old_plan(client: TestClient) -> None:
    _, run = solved_run(client)
    first = release(client, run["id"])
    second = release(client, run["id"])
    assert client.get("/api/floor/plan").json()["id"] == second["id"]
    old = client.get(f"/api/floor/plans/{first['id']}").json()
    assert old["active"] is False
    refused = client.post(f"/api/floor/plans/{first['id']}/jobs/{first['jobs'][0]['id']}/start")
    assert refused.status_code == 409 and "replaced" in refused.json()["detail"]


def test_simulated_shift_records_plausible_actuals_up_to_now(client: TestClient) -> None:
    _, run = solved_run(client)
    plan = release(client, run["id"])
    response = client.post(f"/api/floor/plans/{plan['id']}/simulate")
    assert response.status_code == 200, response.text
    out = response.json()
    now = dt.datetime.fromisoformat(out["server_time"])
    touched = [j for j in out["jobs"] if j["status"] != "planned"]
    assert touched, "a plan that began at midnight should have progressed by now"
    for j in touched:
        assert dt.datetime.fromisoformat(j["actual_start_at"]) <= now
        if j["status"] == "done":
            assert dt.datetime.fromisoformat(j["actual_end_at"]) <= now
    follow_ups = {j["id"]: j for j in out["jobs"] if j["after"]}
    for j in follow_ups.values():
        parent = job(out, j["after"])
        if j["status"] != "planned":
            assert parent["status"] == "done"
            assert j["actual_start_at"] >= parent["actual_end_at"]
    events = client.get(f"/api/floor/plans/{plan['id']}/events").json()
    assert {e["actor"] for e in events} >= {"Demo engineer"}
    assert client.post(f"/api/floor/plans/{plan['id']}/simulate").status_code == 200


def test_replan_keeps_finished_and_running_orders_and_plans_the_rest(client: TestClient) -> None:
    _, run = solved_run(client)
    plan = release(client, run["id"])
    simulated = client.post(f"/api/floor/plans/{plan['id']}/simulate").json()
    started = {j["id"] for j in simulated["jobs"] if j["status"] != "planned"}
    assert started, "the simulated shift should have started something"
    open_ids = {j["id"] for j in simulated["jobs"] if j["status"] == "planned"}

    created = client.post(f"/api/floor/plans/{plan['id']}/replan")
    assert created.status_code == 201, created.text
    scenario = created.json()
    planned = {j["id"] for j in scenario["instance"]["jobs"]}
    assert planned == open_ids  # nothing that was started is planned again
    assert "replan" in scenario["name"]
    for line in scenario["instance"]["resources"]:
        assert line["windows"][0]["start"] > 0  # lines are only free from now on

    replan_run = client.post(
        f"/api/scenarios/{scenario['id']}/solve", json={"time_limit_s": 5, "no_idle": True}
    ).json()
    assert replan_run["status"] in ("OPTIMAL", "FEASIBLE")
    second = release(client, replan_run["id"], released_by="Scheduler")

    ids = {j["id"] for j in second["jobs"]}
    assert ids == open_ids | started  # the whole plan is still on the floor
    for j in second["jobs"]:
        if j["id"] in started:
            before = job(simulated, j["id"])
            assert j["status"] == before["status"]
            assert j["actual_start_at"] == before["actual_start_at"]
            assert j["planned_start_at"] == before["planned_start_at"]
        else:
            assert j["status"] == "planned"
    assert client.get(f"/api/floor/plans/{plan['id']}").json()["active"] is False
    assert client.get("/api/floor/plan").json()["id"] == second["id"]


def test_replan_needs_the_active_plan(client: TestClient) -> None:
    _, run = solved_run(client)
    old = release(client, run["id"])
    release(client, run["id"])
    assert client.post(f"/api/floor/plans/{old['id']}/replan").status_code == 409
