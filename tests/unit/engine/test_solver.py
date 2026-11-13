"""Solver tests on tiny instances with known optima.

Skipped automatically when OR-Tools is not installed; CI installs it and runs them.
"""

import pytest

pytest.importorskip("ortools")

from ortools.sat.python import cp_model  # noqa: E402

from scheduler.engine.cpsat_model import blocked_periods  # noqa: E402
from scheduler.engine.metrics import objective_value, verify_schedule  # noqa: E402
from scheduler.engine.models import (  # noqa: E402
    Job,
    ProblemInstance,
    Resource,
    SolveParams,
    SolveResult,
    SolveStatus,
    Window,
)
from scheduler.engine.solver import map_status, solve  # noqa: E402

PARAMS = SolveParams(time_limit_s=10.0)


def _single(jobs: tuple[Job, ...], windows: tuple[Window, ...], horizon: int) -> ProblemInstance:
    return ProblemInstance(horizon, (Resource("R1", "Line A", windows),), jobs)


def _assert_valid(problem: ProblemInstance, result: SolveResult, *, weighted: bool = True) -> None:
    assert verify_schedule(problem, result.assignments) == []
    assert result.objective == objective_value(problem, result.assignments, weighted=weighted)


def test_single_job_on_time() -> None:
    p = _single((Job("J1", "a", 3, 5, ("R1",)),), (Window(0, 10),), 10)
    r = solve(p, PARAMS)
    assert r.status is SolveStatus.OPTIMAL
    assert r.objective == 0
    assert r.gap == 0
    _assert_valid(p, r)


def test_sequencing_known_optimum() -> None:
    # B first: B ends 2 (on time), A ends 6 (late 2) -> 2. A first would give 4.
    jobs = (Job("A", "a", 4, 4, ("R1",)), Job("B", "b", 2, 2, ("R1",)))
    p = _single(jobs, (Window(0, 10),), 10)
    r = solve(p, PARAMS)
    assert r.status is SolveStatus.OPTIMAL
    assert r.objective == 2
    _assert_valid(p, r)
    starts = {a.job_id: a.start for a in r.assignments}
    assert starts["B"] < starts["A"]


def test_priority_weight_decides_order() -> None:
    jobs = (
        Job("A", "a", 3, 3, ("R1",), priority=5),
        Job("B", "b", 3, 3, ("R1",), priority=1),
    )
    p = _single(jobs, (Window(0, 10),), 10)
    weighted = solve(p, SolveParams(time_limit_s=10.0, weighted=True))
    assert weighted.status is SolveStatus.OPTIMAL
    assert weighted.objective == 3  # B is 3 late with weight 1
    starts = {a.job_id: a.start for a in weighted.assignments}
    assert starts["A"] < starts["B"]
    _assert_valid(p, weighted)

    plain = solve(p, SolveParams(time_limit_s=10.0, weighted=False))
    assert plain.objective == 3
    _assert_valid(p, plain, weighted=False)


def test_calendar_gap_is_respected() -> None:
    # A 5-unit job cannot fit in [0, 4); it must run in [6, 12) and ends at 11 (due 5).
    p = _single((Job("J1", "a", 5, 5, ("R1",)),), (Window(0, 4), Window(6, 12)), 12)
    r = solve(p, PARAMS)
    assert r.status is SolveStatus.OPTIMAL
    assert r.assignments[0].start == 6
    assert r.objective == 6
    _assert_valid(p, r)


def test_job_never_spans_closed_period() -> None:
    # Closed during [4, 6): a 3-unit job must not straddle it.
    jobs = (Job("A", "a", 3, 20, ("R1",)), Job("B", "b", 3, 20, ("R1",)))
    p = _single(jobs, (Window(0, 4), Window(6, 12)), 12)
    r = solve(p, PARAMS)
    assert r.status is SolveStatus.OPTIMAL
    _assert_valid(p, r)


def test_two_resources_run_in_parallel() -> None:
    p = ProblemInstance(
        10,
        (Resource("R1", "a", (Window(0, 10),)), Resource("R2", "b", (Window(0, 10),))),
        (Job("J1", "a", 4, 4, ("R1", "R2")), Job("J2", "b", 4, 4, ("R1", "R2"))),
    )
    r = solve(p, PARAMS)
    assert r.status is SolveStatus.OPTIMAL
    assert r.objective == 0
    assert {a.resource_id for a in r.assignments} == {"R1", "R2"}
    _assert_valid(p, r)


def test_eligibility_is_respected() -> None:
    p = ProblemInstance(
        10,
        (Resource("R1", "a", (Window(0, 10),)), Resource("R2", "b", (Window(0, 10),))),
        (Job("J1", "a", 4, 4, ("R2",)), Job("J2", "b", 4, 4, ("R2",))),
    )
    r = solve(p, PARAMS)
    assert r.status is SolveStatus.OPTIMAL
    assert {a.resource_id for a in r.assignments} == {"R2"}
    assert r.objective == 4
    _assert_valid(p, r)


def test_release_time_is_respected() -> None:
    p = _single((Job("J1", "a", 2, 3, ("R1",), release=5),), (Window(0, 10),), 10)
    r = solve(p, PARAMS)
    assert r.status is SolveStatus.OPTIMAL
    assert r.assignments[0].start == 5
    assert r.objective == 4
    _assert_valid(p, r)


def test_infeasible_when_horizon_too_short() -> None:
    # Each job fits on its own, but two 3-unit jobs cannot share a 5-unit window.
    jobs = (Job("A", "a", 3, 5, ("R1",)), Job("B", "b", 3, 5, ("R1",)))
    r = solve(_single(jobs, (Window(0, 5),), 5), PARAMS)
    assert r.status is SolveStatus.INFEASIBLE
    assert r.assignments == ()
    assert r.objective is None


def test_invalid_model_reports_reasons() -> None:
    p = _single((Job("J1", "a", 3, 5, ()),), (Window(0, 10),), 10)
    r = solve(p, PARAMS)
    assert r.status is SolveStatus.MODEL_INVALID
    assert any("no eligible resources" in m for m in r.messages)


def test_invalid_params_are_rejected() -> None:
    p = _single((Job("J1", "a", 3, 5, ("R1",)),), (Window(0, 10),), 10)
    r = solve(p, SolveParams(time_limit_s=0.0, num_workers=0))
    assert r.status is SolveStatus.MODEL_INVALID
    assert len(r.messages) == 2


def test_repeat_runs_are_deterministic() -> None:
    jobs = tuple(
        Job(f"J{i}", f"job {i}", 2 + i % 3, 6 + i, ("R1", "R2"), priority=1 + i % 5)
        for i in range(8)
    )
    p = ProblemInstance(
        40,
        (
            Resource("R1", "a", (Window(0, 20), Window(24, 40))),
            Resource("R2", "b", (Window(0, 40),)),
        ),
        jobs,
    )
    first = solve(p, PARAMS)
    second = solve(p, PARAMS)
    assert first.status is second.status is SolveStatus.OPTIMAL
    assert first.objective == second.objective
    _assert_valid(p, first)


def test_short_time_limit_never_overclaims() -> None:
    jobs = tuple(
        Job(f"J{i}", f"job {i}", 2 + (i * 7) % 5, 5 + (i * 3) % 20, ("R1", "R2", "R3"),
            priority=1 + i % 5)
        for i in range(40)
    )
    resources = tuple(Resource(f"R{k}", f"line {k}", (Window(0, 200),)) for k in (1, 2, 3))
    p = ProblemInstance(200, resources, jobs)
    r = solve(p, SolveParams(time_limit_s=0.05))
    assert r.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE, SolveStatus.UNKNOWN)
    if r.status is SolveStatus.UNKNOWN:
        assert r.assignments == ()
    else:
        _assert_valid(p, r)
        assert r.best_bound is not None and r.gap is not None
        if r.status is SolveStatus.FEASIBLE:
            assert r.gap > 0


def test_status_mapping() -> None:
    assert map_status(cp_model.OPTIMAL) is SolveStatus.OPTIMAL
    assert map_status(cp_model.FEASIBLE) is SolveStatus.FEASIBLE
    assert map_status(cp_model.INFEASIBLE) is SolveStatus.INFEASIBLE
    assert map_status(cp_model.MODEL_INVALID) is SolveStatus.MODEL_INVALID
    assert map_status(cp_model.UNKNOWN) is SolveStatus.UNKNOWN
    assert map_status(-1) is SolveStatus.UNKNOWN


def test_blocked_periods() -> None:
    r = Resource("R", "x", (Window(6, 12), Window(0, 4), Window(12, 14)))
    assert blocked_periods(r, 20) == [(4, 6), (14, 20)]
    assert blocked_periods(Resource("R", "x", ()), 10) == [(0, 10)]
    assert blocked_periods(Resource("R", "x", (Window(0, 10),)), 10) == []
