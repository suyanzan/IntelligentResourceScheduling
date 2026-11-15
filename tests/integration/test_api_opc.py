"""CPU-hour jobs that merge several lines, through the HTTP API. Needs OR-Tools and PostgreSQL."""

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


def farm(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    window = [{"start": 0, "end": 400}]
    return {
        "horizon": 400,
        "resources": [
            {"id": "A", "name": "Line A", "windows": window, "capacity": 500},
            {"id": "B", "name": "Line B", "windows": window, "capacity": 1000},
        ],
        "jobs": jobs,
    }


def opc_job(job_id: str, work: int, due: int, priority: int = 1) -> dict[str, Any]:
    return {
        "id": job_id, "name": f"MaskOPCOrder {job_id}", "work": work, "due": due,
        "eligible": ["A", "B"], "priority": priority,
    }


def solve(client: TestClient, instance: dict[str, Any], **body: Any) -> dict[str, Any]:
    created = client.post("/api/scenarios", json={"name": "opc", "instance": instance})
    assert created.status_code == 201, created.text
    response = client.post(
        f"/api/scenarios/{created.json()['id']}/solve", json={"time_limit_s": 20, **body}
    )
    assert response.status_code == 201, response.text
    run: dict[str, Any] = response.json()
    return run


def test_opc_preset_has_four_lines_and_cpu_hour_jobs(client: TestClient) -> None:
    response = client.post("/api/data/generate", json={"preset": "opc"})
    assert response.status_code == 201, response.text
    instance = response.json()["instance"]
    assert [r["capacity"] for r in instance["resources"]] == [500, 1000, 1500, 2000]
    assert len(instance["jobs"]) == 20
    assert all(1_000 <= j["work"] <= 150_000 and j["duration"] == 0 for j in instance["jobs"])


def test_a_job_without_duration_or_work_is_rejected(client: TestClient) -> None:
    bad = {"id": "J", "name": "x", "due": 5, "eligible": ["A"]}
    response = client.post("/api/scenarios", json={"name": "x", "instance": farm([bad])})
    assert response.status_code == 422


def test_merged_job_appears_once_per_line_with_one_span(client: TestClient) -> None:
    run = solve(client, farm([opc_job("J1", 150_000, due=100)]))
    assert run["status"] == "OPTIMAL"
    detail = client.get(f"/api/runs/{run['id']}").json()
    rows = detail["assignments"]
    assert sorted(r["resource_id"] for r in rows) == ["A", "B"]
    assert {(r["start"], r["end"]) for r in rows} == {(0, 100)}  # 150000 / (500 + 1000) = 100
    assert all(r["work"] == 150_000 and r["delay"] == 0 and r["tardiness"] == 0 for r in rows)
    assert detail["metrics"]["mean_delay"] == 0
    assert detail["metrics"]["on_time_rate"] == 1.0


def test_mean_delay_sums_late_hours_and_divides_by_all_jobs(client: TestClient) -> None:
    jobs = [opc_job("J1", 15_000, due=10), opc_job("J2", 15_000, due=10), opc_job("J3", 1_500, 80)]
    run = solve(client, farm(jobs))
    assert run["status"] == "OPTIMAL"
    metrics = run["metrics"]
    assert metrics["total_tardiness"] == 10
    assert metrics["mean_delay"] == pytest.approx(10 / 3)
    rows = client.get(f"/api/runs/{run['id']}").json()["assignments"]
    delays = {r["job_id"]: r["delay"] for r in rows}
    assert sorted(delays.values())[-1] == 10  # one order is late by 10 units
    assert min(delays.values()) < 0  # early orders keep their negative delay in the report


def test_comparison_shows_merged_lines_and_mean_delay(client: TestClient) -> None:
    created = client.post(
        "/api/scenarios", json={"name": "opc", "instance": farm([opc_job("J1", 150_000, 100)])}
    ).json()
    sid = created["id"]
    a = client.post(f"/api/scenarios/{sid}/solve", json={"time_limit_s": 20}).json()
    b = client.post(f"/api/scenarios/{sid}/solve", json={"time_limit_s": 20}).json()
    body = client.get("/api/compare", params={"run_a": a["id"], "run_b": b["id"]}).json()
    assert body["better"] == "tie"
    assert body["metrics"]["mean_delay"] == {"a": 0.0, "b": 0.0, "change": 0.0}
    assert body["jobs"][0]["a"]["resource_id"] == "A+B"
    assert body["jobs"][0]["moved"] is False


def line_gaps(rows: list[dict[str, Any]]) -> list[str]:
    """Idle gaps (before the last start of any job) per line, from API assignment rows."""
    last_start = max(r["start"] for r in rows)
    gaps = []
    for line in sorted({r["resource_id"] for r in rows}):
        cursor = 0
        for r in sorted((r for r in rows if r["resource_id"] == line), key=lambda r: r["start"]):
            if r["start"] >= last_start:
                break
            if r["start"] > cursor:
                gaps.append(f"{line}: idle {cursor}-{r['start']}")
            cursor = max(cursor, r["end"])
        if cursor < last_start:
            gaps.append(f"{line}: idle {cursor}-{last_start}")
    return gaps


def test_no_idle_run_is_recorded_and_keeps_lines_busy(client: TestClient) -> None:
    generated = client.post("/api/data/generate", json={"preset": "opc"}).json()
    response = client.post(
        f"/api/scenarios/{generated['id']}/solve", json={"time_limit_s": 20, "no_idle": True}
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["no_idle"] is True
    assert run["status"] in ("OPTIMAL", "FEASIBLE")
    rows = client.get(f"/api/runs/{run['id']}").json()["assignments"]
    assert line_gaps(rows) == []
    assert run["metrics"]["mean_delay"] < 20  # the start schedule alone is ~2.7 h


def test_no_idle_is_off_by_default(client: TestClient) -> None:
    run = solve(client, farm([opc_job("J1", 15_000, due=10)]))
    assert run["no_idle"] is False


def test_no_idle_with_a_release_time_is_solved(client: TestClient) -> None:
    job = opc_job("J1", 15_000, due=10) | {"release": 3}
    run = solve(client, farm([job]), no_idle=True)
    assert run["status"] in ("OPTIMAL", "FEASIBLE")
    assert run["no_idle"] is True
    rows = client.get(f"/api/runs/{run['id']}").json()["assignments"]
    assert min(r["start"] for r in rows) >= 3


def test_live_preset_round_trips_and_solves_with_links_and_cycle_points(
    client: TestClient,
) -> None:
    generated = client.post("/api/data/generate", json={"preset": "opc_live"}).json()
    jobs = {j["id"]: j for j in generated["instance"]["jobs"]}
    assert generated["instance"]["max_merge_capacity"] == 3000
    assert jobs["R001"]["after"] == "O001"
    assert any(j["layer"] == "DIFFUSION" and j["cycle_limit"] == 12 for j in jobs.values())

    run = client.post(
        f"/api/scenarios/{generated['id']}/solve", json={"time_limit_s": 20, "no_idle": True}
    ).json()
    assert run["status"] in ("OPTIMAL", "FEASIBLE")
    assert run["metrics"]["cycle_points"] >= 0
    rows = client.get(f"/api/runs/{run['id']}").json()["assignments"]
    by_job: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_job.setdefault(row["job_id"], []).append(row)
    for code, job in jobs.items():
        if job["after"]:
            assert by_job[code][0]["start"] >= by_job[job["after"]][0]["end"]
        caps = {"A": 500, "B": 1000, "C": 1500, "D": 2000, "E": 1500}
        used = sum(caps[r["resource_id"]] for r in by_job[code])
        assert used <= 3000
    flagged = {r["job_id"] for r in rows if r["over_cycle"]}
    assert len(flagged) == run["metrics"]["cycle_points"]
