"""Jobs measured in capacity-hours that may merge several resources (no solver needed)."""

import pytest

from scheduler.engine.metrics import compute_metrics, job_delays, objective_value, verify_schedule
from scheduler.engine.models import (
    Assignment,
    Job,
    ProblemInstance,
    Resource,
    Window,
    duration_on,
)
from scheduler.engine.serialization import (
    instance_from_dict,
    instance_hash,
    instance_to_dict,
)
from scheduler.engine.validation import validate_instance

A = Resource("A", "Line A", (Window(0, 400),), capacity=500)
B = Resource("B", "Line B", (Window(0, 400),), capacity=1000)


def opc(job_id: str, work: int, due: int, priority: int = 1) -> Job:
    return Job(
        job_id, job_id, duration=0, due=due, eligible=("A", "B"), priority=priority, work=work
    )


def problem(*jobs: Job) -> ProblemInstance:
    return ProblemInstance(horizon=400, resources=(A, B), jobs=jobs)


def test_duration_scales_with_merged_capacity() -> None:
    job = opc("J", 150_000, due=100)
    assert duration_on(job, [A]) == 300
    assert duration_on(job, [B]) == 150
    assert duration_on(job, [A, B]) == 100


def test_duration_rounds_up() -> None:
    assert duration_on(opc("J", 1001, due=5), [B]) == 2
    assert duration_on(Job("C", "C", duration=7, due=9, eligible=("A",)), [A]) == 7


def test_merged_schedule_is_valid_and_counted_once() -> None:
    p = problem(opc("J1", 150_000, due=100))
    rows = [Assignment("J1", "A", 0, 100), Assignment("J1", "B", 0, 100)]
    assert verify_schedule(p, rows) == []
    metrics = compute_metrics(p, rows)
    assert metrics.job_count == 1 and metrics.on_time_count == 1
    assert metrics.utilization["A"] == 1.0 and metrics.utilization["B"] == 1.0


def test_verifier_rejects_wrong_duration_and_unshared_times() -> None:
    p = problem(opc("J1", 150_000, due=100))
    wrong = [Assignment("J1", "A", 0, 100)]  # A alone needs 300 units
    assert any("spans 100 units but its duration is 300" in v for v in verify_schedule(p, wrong))
    split = [Assignment("J1", "A", 0, 100), Assignment("J1", "B", 10, 110)]
    assert any("share one start and end" in v for v in verify_schedule(p, split))


def test_merged_jobs_cannot_overlap_on_a_shared_line() -> None:
    p = problem(opc("J1", 15_000, due=10), opc("J2", 15_000, due=10))
    rows = [
        Assignment("J1", "A", 0, 10), Assignment("J1", "B", 0, 10),
        Assignment("J2", "B", 5, 15),  # B alone: 15 units, but overlaps J1 on B
    ]
    assert any("overlap on resource 'B'" in v for v in verify_schedule(p, rows))


def test_delay_report_counts_only_late_jobs_but_divides_by_all_jobs() -> None:
    p = problem(opc("J1", 15_000, due=10), opc("J2", 15_000, due=10), opc("J3", 1000, due=50))
    rows = [
        Assignment("J1", "A", 0, 10), Assignment("J1", "B", 0, 10),
        Assignment("J2", "A", 10, 20), Assignment("J2", "B", 10, 20),
        Assignment("J3", "B", 20, 21),
    ]
    assert job_delays(p, rows) == {"J1": 0, "J2": 10, "J3": -29}  # early jobs keep a negative value
    metrics = compute_metrics(p, rows)
    assert metrics.total_tardiness == 10
    assert metrics.mean_delay == pytest.approx(10 / 3)
    assert objective_value(p, rows, weighted=False) == 10


def test_validation_of_work_and_capacity() -> None:
    bad_cap = Resource("X", "X", (Window(0, 10),), capacity=0)
    p = ProblemInstance(
        horizon=10,
        resources=(bad_cap,),
        jobs=(Job("J", "J", duration=0, due=5, eligible=("X",), work=0),),
    )
    issues = validate_instance(p)
    assert any("capacity must be at least 1" in i for i in issues)
    assert any("work must be positive" in i for i in issues)


def test_work_job_that_cannot_finish_even_when_merged() -> None:
    issues = validate_instance(problem(opc("J", 1_000_000, due=10)))  # 1e6 / 1500 > 400
    assert any("does not fit" in i for i in issues)


def test_too_many_eligible_resources_for_merging() -> None:
    resources = tuple(Resource(f"R{i}", f"R{i}", (Window(0, 100),), capacity=10) for i in range(9))
    job = Job("J", "J", duration=0, due=5, eligible=tuple(r.id for r in resources), work=100)
    issues = validate_instance(ProblemInstance(horizon=100, resources=resources, jobs=(job,)))
    assert any("at most 8" in i for i in issues)


def test_serialization_round_trip_and_classic_hash_unchanged() -> None:
    p = problem(opc("J1", 150_000, due=100))
    assert instance_from_dict(instance_to_dict(p)) == p
    classic = ProblemInstance(
        horizon=10,
        resources=(Resource("R", "R", (Window(0, 10),)),),
        jobs=(Job("J", "J", duration=2, due=5, eligible=("R",)),),
    )
    data = instance_to_dict(classic)
    assert "capacity" not in data["resources"][0] and "work" not in data["jobs"][0]
    assert instance_hash(classic) == instance_hash(instance_from_dict(data))
