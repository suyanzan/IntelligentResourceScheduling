from dataclasses import replace

import pytest

from scheduler.engine.metrics import (
    available_units,
    compute_metrics,
    daily_capacity,
    objective_value,
    tardiness,
    verify_schedule,
)
from scheduler.engine.models import Assignment, Job, ProblemInstance, Window


def _has(violations: list[str], *needles: str) -> bool:
    return any(all(n in v for n in needles) for v in violations)


def test_tardiness_is_never_negative() -> None:
    job = Job("J", "x", duration=2, due=10, eligible=("R",))
    assert tardiness(job, 8) == 0
    assert tardiness(job, 10) == 0
    assert tardiness(job, 13) == 3


def test_objective_weighted_and_unweighted(
    problem: ProblemInstance, valid_assignments: list[Assignment]
) -> None:
    # Only J2 is late: tardiness 10, priority 2.
    assert objective_value(problem, valid_assignments, weighted=False) == 10
    assert objective_value(problem, valid_assignments, weighted=True) == 20


def test_objective_unknown_job_raises(problem: ProblemInstance) -> None:
    with pytest.raises(ValueError, match="unknown job id"):
        objective_value(problem, [Assignment("J99", "R1", 0, 1)])


def test_available_units() -> None:
    windows = [Window(0, 8), Window(10, 18)]
    assert available_units(windows, 0) == 0
    assert available_units(windows, 8) == 8
    assert available_units(windows, 9) == 8
    assert available_units(windows, 16) == 14
    assert available_units(windows, 100) == 16


def test_compute_metrics_makespan_basis(
    problem: ProblemInstance, valid_assignments: list[Assignment]
) -> None:
    m = compute_metrics(problem, valid_assignments)
    assert m.job_count == 3
    assert m.on_time_count == 2
    assert m.on_time_rate == pytest.approx(2 / 3)
    assert m.total_tardiness == 10
    assert m.weighted_tardiness == 20
    assert m.makespan == 16
    # R1 busy 4 + 6 = 10 of 14 available units in [0, 16); R2 busy 5 of 16.
    assert m.utilization["R1"] == pytest.approx(10 / 14)
    assert m.utilization["R2"] == pytest.approx(5 / 16)


def test_compute_metrics_horizon_basis(
    problem: ProblemInstance, valid_assignments: list[Assignment]
) -> None:
    m = compute_metrics(problem, valid_assignments, utilization_basis="horizon")
    assert m.utilization["R1"] == pytest.approx(10 / 16)
    assert m.utilization["R2"] == pytest.approx(5 / 24)


def test_compute_metrics_idle_resource_and_empty_schedule(problem: ProblemInstance) -> None:
    m = compute_metrics(problem, [])
    assert m.job_count == 0
    assert m.on_time_rate == 1.0
    assert m.total_tardiness == 0
    assert m.makespan == 0
    assert m.utilization == {"R1": 0.0, "R2": 0.0}


def test_valid_schedule_has_no_violations(
    problem: ProblemInstance, valid_assignments: list[Assignment]
) -> None:
    assert verify_schedule(problem, valid_assignments) == []


def test_missing_job(problem: ProblemInstance, valid_assignments: list[Assignment]) -> None:
    violations = verify_schedule(problem, valid_assignments[:2])
    assert _has(violations, "J3", "no assignment")


def test_job_assigned_twice(problem: ProblemInstance, valid_assignments: list[Assignment]) -> None:
    violations = verify_schedule(problem, [*valid_assignments, Assignment("J1", "R2", 10, 14)])
    assert _has(violations, "J1", "cannot merge")


def test_unknown_job_and_resource(
    problem: ProblemInstance, valid_assignments: list[Assignment]
) -> None:
    extra = [Assignment("J99", "R1", 0, 1), Assignment("J1", "R99", 0, 4)]
    violations = verify_schedule(problem, [*valid_assignments, *extra])
    assert _has(violations, "unknown job", "J99")
    assert _has(violations, "unknown resource", "R99")


def test_ineligible_resource(problem: ProblemInstance, valid_assignments: list[Assignment]) -> None:
    # J2 is only eligible for R1.
    bad = [valid_assignments[0], Assignment("J2", "R2", 6, 12), valid_assignments[2]]
    assert _has(verify_schedule(problem, bad), "J2", "not eligible")


def test_wrong_duration(problem: ProblemInstance, valid_assignments: list[Assignment]) -> None:
    bad = [Assignment("J1", "R1", 0, 3), *valid_assignments[1:]]
    assert _has(verify_schedule(problem, bad), "J1", "duration is 4")


def test_before_release_time(problem: ProblemInstance, valid_assignments: list[Assignment]) -> None:
    jobs = (replace(problem.jobs[0], release=2), *problem.jobs[1:])
    violations = verify_schedule(replace(problem, jobs=jobs), valid_assignments)
    assert _has(violations, "J1", "release time")


def test_beyond_horizon(problem: ProblemInstance, valid_assignments: list[Assignment]) -> None:
    short = replace(problem, horizon=12)
    assert _has(verify_schedule(short, valid_assignments), "J2", "beyond the horizon")


def test_job_spanning_closed_period(
    problem: ProblemInstance, valid_assignments: list[Assignment]
) -> None:
    # R1 is closed during [8, 10); J2 at [4, 10) crosses that gap.
    bad = [valid_assignments[0], Assignment("J2", "R1", 4, 10), valid_assignments[2]]
    assert _has(verify_schedule(problem, bad), "J2", "single availability window")


def test_overlap_on_same_resource(
    problem: ProblemInstance, valid_assignments: list[Assignment]
) -> None:
    bad = [Assignment("J1", "R1", 0, 4), Assignment("J2", "R1", 3, 9), valid_assignments[2]]
    assert _has(verify_schedule(problem, bad), "J1", "J2", "overlap")


def test_back_to_back_jobs_do_not_overlap(problem: ProblemInstance) -> None:
    ok = [Assignment("J1", "R1", 0, 4), Assignment("J3", "R2", 0, 5), Assignment("J2", "R1", 4, 10)]
    # J2 crosses the closed period, so it is invalid for that reason only, not for overlap.
    violations = verify_schedule(problem, ok)
    assert not _has(violations, "overlap")
    assert _has(violations, "J2", "single availability window")


def test_daily_capacity() -> None:
    windows = [Window(0, 8), Window(10, 18), Window(24, 30)]
    assert daily_capacity(windows, 24) == 16  # day 0: 8 + 8, day 1: 6
    assert daily_capacity([], 24) == 0
    # A window crossing midnight counts towards both days.
    assert daily_capacity([Window(20, 30)], 24) == 6
    with pytest.raises(ValueError, match="units_per_day"):
        daily_capacity(windows, 0)
