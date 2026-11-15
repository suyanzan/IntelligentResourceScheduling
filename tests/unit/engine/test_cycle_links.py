"""Merge capacity cap, 'after' links and cycle points (no solver needed)."""

from dataclasses import replace

from scheduler.engine.metrics import compute_metrics, objective_value, verify_schedule
from scheduler.engine.models import (
    Assignment,
    Job,
    ProblemInstance,
    Resource,
    Window,
    option_sets,
    over_cycle,
)
from scheduler.engine.serialization import instance_from_dict, instance_hash, instance_to_dict
from scheduler.engine.validation import validate_instance

LINES = tuple(
    Resource(code, f"Line {code}", (Window(0, 200),), capacity=cap)
    for code, cap in (("A", 500), ("B", 1000), ("C", 1500), ("D", 2000))
)
BY_ID = {r.id: r for r in LINES}


def job(job_id: str, work: int = 1000, **kwargs: object) -> Job:
    base = {
        "id": job_id, "name": job_id, "duration": 0, "due": 100,
        "eligible": ("A", "B", "C", "D"), "work": work,
    }
    return Job(**{**base, **kwargs})  # type: ignore[arg-type]


def problem(*jobs: Job, **kwargs: object) -> ProblemInstance:
    return ProblemInstance(horizon=200, resources=LINES, jobs=jobs, **kwargs)  # type: ignore[arg-type]


def test_cap_limits_merged_capacity() -> None:
    free = option_sets(job("J"), BY_ID)
    capped = option_sets(job("J"), BY_ID, max_capacity=3000)
    assert len(free) == 15
    sums = {sum(r.capacity for r in s) for s in capped}
    assert max(sums) == 3000
    assert len(capped) < len(free)
    names = {"".join(r.id for r in s) for s in capped}
    assert "ABC" in names and "BD" in names
    assert "CD" not in names and "ABCD" not in names


def test_cycle_points() -> None:
    diffusion = job("D1", cycle_limit=12, release=10, layer="DIFFUSION")
    assert not over_cycle(diffusion, 22)
    assert over_cycle(diffusion, 23)
    assert not over_cycle(job("X"), 1000)


def test_objective_and_metrics_count_cycle_points() -> None:
    d1 = job("D1", cycle_limit=2, due=500)
    d2 = job("D2", cycle_limit=2, due=500)
    p = problem(d1, d2, cycle_penalty=50)
    rows = (
        Assignment("D1", "D", 0, 2), Assignment("D2", "D", 2, 5),
    )
    assert compute_metrics(p, rows).cycle_points == 1
    assert objective_value(p, rows) == 50


def test_verifier_checks_after_and_cap() -> None:
    first, second = job("F"), job("S", after="F")
    p = problem(first, second, max_merge_capacity=3000)
    ok = (Assignment("F", "A", 0, 2), Assignment("S", "A", 2, 4))
    assert verify_schedule(p, ok) == []
    early = (Assignment("F", "A", 0, 2), Assignment("S", "B", 1, 3))
    assert any("before job 'F' ends" in v for v in verify_schedule(p, early))
    big = (
        Assignment("F", "C", 0, 1), Assignment("F", "D", 0, 1), Assignment("S", "A", 5, 7),
    )
    assert any("above the limit" in v for v in verify_schedule(p, big))


def test_validation_of_links() -> None:
    p = problem(job("A1", after="A2"), job("A2", after="A1"), job("B1", after="nope"),
                job("B2", cycle_limit=0))
    text = "; ".join(validate_instance(p))
    assert "loop" in text and "unknown job 'nope'" in text and "cycle_limit" in text
    assert validate_instance(problem(job("X"), job("Y", after="X"))) == []


def test_serialization_round_trip_and_default_hash() -> None:
    plain = problem(job("X"))
    assert "max_merge_capacity" not in instance_to_dict(plain)
    rich = problem(
        job("X", cycle_limit=12, layer="DIFFUSION"), job("Y", after="X"),
        max_merge_capacity=3000, cycle_penalty=80,
    )
    again = instance_from_dict(instance_to_dict(rich))
    assert again == rich
    other = replace(rich, cycle_penalty=50)
    assert instance_hash(again) == instance_hash(rich) != instance_hash(other)
