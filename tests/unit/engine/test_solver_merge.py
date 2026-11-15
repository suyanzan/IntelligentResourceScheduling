"""Solving with merged resources. Needs OR-Tools."""

import pytest

pytest.importorskip("ortools")

from scheduler.engine.metrics import compute_metrics, verify_schedule  # noqa: E402
from scheduler.engine.models import (  # noqa: E402
    Job,
    ProblemInstance,
    Resource,
    SolveParams,
    SolveResult,
    SolveStatus,
    Window,
)
from scheduler.engine.solver import solve  # noqa: E402

A = Resource("A", "Line A", (Window(0, 400),), capacity=500)
B = Resource("B", "Line B", (Window(0, 400),), capacity=1000)


def opc(job_id: str, work: int, due: int, priority: int = 1) -> Job:
    return Job(
        job_id, job_id, duration=0, due=due, eligible=("A", "B"), priority=priority, work=work
    )


def run(*jobs: Job, weighted: bool = True) -> tuple[ProblemInstance, SolveResult]:
    problem = ProblemInstance(horizon=400, resources=(A, B), jobs=jobs)
    return problem, solve(problem, SolveParams(time_limit_s=20, weighted=weighted))


def test_merging_two_lines_makes_the_due_date() -> None:
    problem, result = run(opc("J1", 150_000, due=100))
    assert result.status is SolveStatus.OPTIMAL
    assert result.objective == 0
    assert {a.resource_id for a in result.assignments} == {"A", "B"}
    assert {(a.start, a.end) for a in result.assignments} == {(0, 100)}
    assert verify_schedule(problem, result.assignments) == []


def test_two_jobs_compete_for_the_same_lines() -> None:
    # Each needs both lines for 10 units; the second one is unavoidably 10 units late.
    problem, result = run(opc("J1", 15_000, due=10), opc("J2", 15_000, due=10))
    assert result.status is SolveStatus.OPTIMAL
    assert result.objective == 10
    assert verify_schedule(problem, result.assignments) == []
    metrics = compute_metrics(problem, result.assignments)
    assert metrics.total_tardiness == 10 and metrics.mean_delay == pytest.approx(5.0)


def test_small_job_can_use_one_line_while_the_big_one_uses_the_other() -> None:
    # J1 takes B alone (10 units), J2 takes A alone (2 units); both are on time.
    problem, result = run(opc("J1", 10_000, due=10), opc("J2", 1_000, due=10))
    assert result.status is SolveStatus.OPTIMAL and result.objective == 0
    assert verify_schedule(problem, result.assignments) == []


def test_priority_decides_who_gets_the_lines_first() -> None:
    problem, result = run(
        opc("LOW", 15_000, due=10, priority=1), opc("HIGH", 15_000, due=10, priority=5)
    )
    assert result.status is SolveStatus.OPTIMAL
    ends = {a.job_id: a.end for a in result.assignments}
    assert ends["HIGH"] == 10 and ends["LOW"] == 20
    assert result.objective == 10  # LOW is late by 10 at weight 1


def test_no_idle_keeps_every_line_busy_until_the_last_job_starts() -> None:
    problem = ProblemInstance(
        horizon=400,
        resources=(A, B),
        jobs=tuple(opc(f"J{i}", 1_000 * (i + 1), due=10 * (i + 1)) for i in range(6)),
    )
    result = solve(problem, SolveParams(time_limit_s=20, no_idle=True))
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
    assert verify_schedule(problem, result.assignments, no_idle=True) == []


def test_no_idle_on_the_opc_sample_is_at_least_as_good_as_the_start_schedule() -> None:
    from scheduler.engine.heuristic import sequential_merge_schedule
    from scheduler.engine.metrics import objective_value
    from scheduler.synthetic.generator import preset

    problem = preset("opc")
    result = solve(problem, SolveParams(time_limit_s=20, no_idle=True))
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
    assert verify_schedule(problem, result.assignments, no_idle=True) == []
    start = sequential_merge_schedule(problem)
    assert start is not None
    assert result.objective is not None
    assert result.objective <= objective_value(problem, start)


def test_no_idle_needs_release_times_of_zero() -> None:
    late = Job("J", "J", duration=0, due=50, eligible=("A", "B"), work=1_000, release=5)
    result = solve(
        ProblemInstance(horizon=100, resources=(A, B), jobs=(late,)),
        SolveParams(time_limit_s=5, no_idle=True),
    )
    assert result.status is SolveStatus.MODEL_INVALID
    assert any("released at time 0" in m for m in result.messages)
