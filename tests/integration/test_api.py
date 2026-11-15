"""HTTP API tests (no solver needed): CRUD, validation, error mapping, synthetic data."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from scheduler.api.deps import get_session
from scheduler.api.main import create_app


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client


def instance(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "horizon": 24,
        "resources": [{"id": "R1", "name": "Line A", "windows": [{"start": 0, "end": 12}]}],
        "jobs": [
            {
                "id": "J1",
                "name": "Order 1",
                "duration": 3,
                "due": 5,
                "eligible": ["R1"],
                "priority": 2,
            }
        ],
    }
    payload.update(overrides)
    return payload


def create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post(
        "/api/scenarios", json={"name": "Demo", "instance": instance(**overrides)}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_and_read_back(client: TestClient) -> None:
    created = create(client)
    assert created["name"] == "Demo"
    assert (created["resource_count"], created["job_count"], created["run_count"]) == (1, 1, 0)
    assert created["time_unit_minutes"] == 60

    fetched = client.get(f"/api/scenarios/{created['id']}").json()
    assert fetched["instance"]["horizon"] == 24
    assert fetched["instance"]["resources"][0]["daily_capacity_units"] == 12
    assert fetched["instance"]["jobs"][0] == {
        "id": "J1",
        "name": "Order 1",
        "duration": 3,
        "due": 5,
        "eligible": ["R1"],
        "priority": 2,
        "release": 0,
        "work": None,
    }


def test_list_includes_counts_newest_first(client: TestClient) -> None:
    first = create(client)
    second = create(client)
    listed = client.get("/api/scenarios").json()
    ids = [s["id"] for s in listed]
    assert ids.index(second["id"]) < ids.index(first["id"])
    assert all(s["job_count"] == 1 for s in listed if s["id"] in (first["id"], second["id"]))


@pytest.mark.parametrize(
    "bad_job",
    [
        {"id": "J1", "name": "x", "duration": -1, "due": 5, "eligible": ["R1"]},
        {"id": "J1", "name": "x", "duration": 0, "due": 5, "eligible": ["R1"]},
        {"id": "J1", "name": "x", "duration": 2, "due": 5, "eligible": ["R1"], "priority": 9},
        {"id": "", "name": "x", "duration": 2, "due": 5, "eligible": ["R1"]},
        {"name": "x", "duration": 2, "due": 5, "eligible": ["R1"]},
    ],
)
def test_malformed_requests_get_field_errors(client: TestClient, bad_job: dict[str, Any]) -> None:
    response = client.post(
        "/api/scenarios", json={"name": "x", "instance": instance(jobs=[bad_job])}
    )
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {"jobs": [{"id": "J1", "name": "x", "duration": 2, "due": 5, "eligible": []}]},
            "no eligible resources",
        ),
        (
            {"jobs": [{"id": "J1", "name": "x", "duration": 2, "due": 5, "eligible": ["R9"]}]},
            "unknown resource",
        ),
        (
            {"jobs": [{"id": "J1", "name": "x", "duration": 20, "due": 30, "eligible": ["R1"]}]},
            "cannot fit",
        ),
        (
            {
                "resources": [
                    {
                        "id": "R1",
                        "name": "a",
                        "windows": [{"start": 0, "end": 10}, {"start": 5, "end": 12}],
                    }
                ]
            },
            "overlapping windows",
        ),
        (
            {"resources": [{"id": "R1", "name": "a", "windows": [{"start": 8, "end": 4}]}]},
            "empty or reversed",
        ),
    ],
)
def test_invalid_instances_get_readable_issues(
    client: TestClient, overrides: dict[str, Any], expected: str
) -> None:
    response = client.post("/api/scenarios", json={"name": "x", "instance": instance(**overrides)})
    assert response.status_code == 422
    body = response.json()
    assert any(expected in issue for issue in body["issues"]), body


def test_unknown_ids_return_404(client: TestClient) -> None:
    missing = 999_999
    assert client.get(f"/api/scenarios/{missing}").status_code == 404
    assert client.delete(f"/api/scenarios/{missing}").status_code == 404
    assert client.get(f"/api/scenarios/{missing}/runs").status_code == 404
    assert client.post(f"/api/scenarios/{missing}/solve").status_code == 404
    assert client.post(f"/api/scenarios/{missing}/clone", json={"name": "c"}).status_code == 404
    assert client.get(f"/api/runs/{missing}").status_code == 404
    assert client.put(f"/api/scenarios/{missing}/instance", json=instance()).status_code == 404


def test_non_integer_id_is_a_validation_error(client: TestClient) -> None:
    assert client.get("/api/scenarios/abc").status_code == 422


def test_delete_then_gone(client: TestClient) -> None:
    created = create(client)
    assert client.delete(f"/api/scenarios/{created['id']}").status_code == 204
    assert client.get(f"/api/scenarios/{created['id']}").status_code == 404


def test_clone_and_replace_instance(client: TestClient) -> None:
    created = create(client)
    clone = client.post(f"/api/scenarios/{created['id']}/clone", json={"name": "Copy"})
    assert clone.status_code == 201
    assert clone.json()["name"] == "Copy"
    assert clone.json()["id"] != created["id"]

    replaced = client.put(
        f"/api/scenarios/{clone.json()['id']}/instance",
        json=instance(
            jobs=[
                {"id": "A", "name": "a", "duration": 1, "due": 2, "eligible": ["R1"]},
                {"id": "B", "name": "b", "duration": 1, "due": 2, "eligible": ["R1"]},
            ]
        ),
    )
    assert replaced.status_code == 200
    assert replaced.json()["job_count"] == 2
    # The original is untouched.
    assert client.get(f"/api/scenarios/{created['id']}").json()["job_count"] == 1


def test_replace_with_invalid_instance_changes_nothing(client: TestClient) -> None:
    created = create(client)
    bad = instance(jobs=[{"id": "J1", "name": "x", "duration": 2, "due": 5, "eligible": []}])
    assert client.put(f"/api/scenarios/{created['id']}/instance", json=bad).status_code == 422
    assert client.get(f"/api/scenarios/{created['id']}").json()["job_count"] == 1


def test_generate_preset(client: TestClient) -> None:
    response = client.post("/api/data/generate", json={"preset": "tiny"})
    assert response.status_code == 201
    body = response.json()
    assert (body["resource_count"], body["job_count"]) == (2, 6)
    assert body["horizon_start"] == "2026-01-05"
    assert body["seed"] == 1
    assert body["instance"]["horizon"] == 7 * 24


def test_generate_is_deterministic(client: TestClient) -> None:
    payload = {"seed": 7, "num_jobs": 12, "num_resources": 3, "num_days": 10}
    first = client.post("/api/data/generate", json=payload).json()
    second = client.post("/api/data/generate", json=payload).json()
    assert first["id"] != second["id"]
    assert first["instance"] == second["instance"]
    assert first["job_count"] == 12


@pytest.mark.parametrize(
    "payload",
    [
        {"preset": "huge"},
        {"preset": "tiny", "seed": 3},
        {"num_jobs": 0},
        {"num_days": 1},
        {"num_resources": 500},
    ],
)
def test_generate_rejects_bad_requests(client: TestClient, payload: dict[str, Any]) -> None:
    assert client.post("/api/data/generate", json=payload).status_code == 422
