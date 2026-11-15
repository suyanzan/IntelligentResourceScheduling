"""Solving with the merge cap, 'after' links and cycle points. Needs OR-Tools."""

import pytest

pytest.importorskip("ortools")

from scheduler.engine.metrics import compute_metrics, verify_schedule  # noqa: E402
from scheduler.engine.models import (  # noqa: E402
    Job,
    ProblemInstance,
    Resource,
    SolveParams,
    SolveStatus,
    Window,
)
from scheduler.engine.solver import solve  # noqa: E402

LINES = tuple(
    Resource(code, f"Line {code}", (Window(0, 300),), capacity=cap)
    for code, cap in (("A", 500), ("B", 1000), ("C", 1500), ("D", 2000))
)


def job(job_id: str, work: int, due: int, **kwargs: object) -> Job:
    base = {
        "id": job_id, "name": job_id, "duration": 0, "due": due, "priority": 1,
        "eligible": ("A", "B", "C", "D"), "work": work,
    }
    return Job(**{**base, **kwargs})  # type: ignore[arg-type]


def test_merge_cap_is_respected() -> None:
    problem = ProblemInstance(
        horizon=300, resources=LINES, jobs=(job("J", 150_000, due=30),), max_merge_capacity=3000
    )
    result = solve(problem, SolveParams(time_limit_s=20))
    assert result.status is SolveStatus.OPTIMAL
    assert sum(LINES[["A", "B", "C", "D"].index(a.resource_id)].capacity
               for a in result.assignments) <= 3000
    assert verify_schedule(problem, result.assignments) == []
    assert compute_metrics(problem, result.assignments).total_tardiness > 0  # 3000 -> 50 h > 30


def test_after_job_waits_for_its_predecessor() -> None:
    first = job("OPC", 20_000, due=100)
    follow = job("RP", 8_400, due=100, after="OPC")
    problem = ProblemInstance(horizon=300, resources=LINES, jobs=(first, follow))
    result = solve(problem, SolveParams(time_limit_s=20))
    assert result.status is SolveStatus.OPTIMAL
    ends = {a.job_id: a.end for a in result.assignments}
    starts = {a.job_id: a.start for a in result.assignments}
    assert starts["RP"] >= ends["OPC"]
    assert verify_schedule(problem, result.assignments) == []


def test_diffusion_job_jumps_the_queue_on_a_free_line() -> None:
    # A, B, C are busy with order 001 until t=40; D is free. The DIFFUSION job arrives at t=10
    # with a 12 h cycle limit and must run on D alone to avoid a cycle point.
    busy = tuple(
        Resource(r.id, r.name, (Window(40, 300),), r.capacity) for r in LINES[:3]
    )
    lines = (*busy, LINES[3])
    diffusion = job(
        "DIFF", 20_000, due=200, release=10, cycle_limit=12, layer="DIFFUSION",
        eligible=("A", "B", "C", "D"),
    )
    problem = ProblemInstance(
        horizon=300, resources=lines, jobs=(diffusion,), max_merge_capacity=3000
    )
    result = solve(problem, SolveParams(time_limit_s=20))
    assert result.status is SolveStatus.OPTIMAL
    assert {a.resource_id for a in result.assignments} == {"D"}
    assert compute_metrics(problem, result.assignments).cycle_points == 0
    assert result.objective == 0


def test_a_tiny_time_limit_still_returns_a_verified_feasible_schedule() -> None:
    from scheduler.synthetic.generator import preset

    problem = preset("opc_live")
    result = solve(problem, SolveParams(time_limit_s=0.05, no_idle=True))
    assert result.status in (SolveStatus.FEASIBLE, SolveStatus.OPTIMAL)
    assert result.assignments
    assert verify_schedule(problem, result.assignments, no_idle=True) == []
