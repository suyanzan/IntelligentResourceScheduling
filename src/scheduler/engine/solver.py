"""Solver wrapper: validation, CP-SAT solve, status mapping and result verification.

``OPTIMAL`` is only reported when CP-SAT proves optimality. Every returned schedule is re-checked
by :func:`scheduler.engine.metrics.verify_schedule` and its objective is recomputed independently;
a disagreement raises :class:`ScheduleVerificationError` instead of returning a wrong answer.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from scheduler.engine.cpsat_model import BuiltModel, build_model
from scheduler.engine.heuristic import best_start_schedule
from scheduler.engine.metrics import objective_value, verify_schedule
from scheduler.engine.models import (
    Assignment,
    ProblemInstance,
    SolveParams,
    SolveResult,
    SolveStatus,
)
from scheduler.engine.validation import validate_instance


class ScheduleVerificationError(RuntimeError):
    """The solver returned a schedule that fails independent verification."""


def map_status(cp_status: cp_model.CpSolverStatus) -> SolveStatus:
    """Map a CP-SAT status code to :class:`SolveStatus` (never upgrades FEASIBLE)."""
    mapping: dict[cp_model.CpSolverStatus, SolveStatus] = {
        cp_model.OPTIMAL: SolveStatus.OPTIMAL,
        cp_model.FEASIBLE: SolveStatus.FEASIBLE,
        cp_model.INFEASIBLE: SolveStatus.INFEASIBLE,
        cp_model.MODEL_INVALID: SolveStatus.MODEL_INVALID,
    }
    return mapping.get(cp_status, SolveStatus.UNKNOWN)


def validate_params(params: SolveParams) -> list[str]:
    issues: list[str] = []
    if params.time_limit_s <= 0:
        issues.append(f"time_limit_s must be positive, got {params.time_limit_s}")
    if params.num_workers < 1:
        issues.append(f"num_workers must be at least 1, got {params.num_workers}")
    return issues


def solve(problem: ProblemInstance, params: SolveParams | None = None) -> SolveResult:
    """Solve ``problem`` and return a verified :class:`SolveResult`."""
    params = params or SolveParams()

    issues = [
        *validate_instance(problem),
        *validate_params(params),
    ]
    if issues:
        return SolveResult(status=SolveStatus.MODEL_INVALID, messages=tuple(issues))

    built = build_model(problem, weighted=params.weighted, no_idle=params.no_idle)
    start = best_start_schedule(problem, weighted=params.weighted, no_idle=params.no_idle)
    if start is not None:
        _add_start_hint(built, start)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = params.time_limit_s
    solver.parameters.num_workers = params.num_workers
    solver.parameters.random_seed = params.random_seed
    solver.parameters.repair_hint = True  # complete the hint's helper variables if needed

    status = map_status(solver.solve(built.model))
    wall = solver.wall_time

    if status is SolveStatus.UNKNOWN and start is not None:
        return _start_result(problem, start, params, wall, "the solver found no schedule")

    if status in (SolveStatus.INFEASIBLE, SolveStatus.UNKNOWN, SolveStatus.MODEL_INVALID):
        return SolveResult(status=status, wall_time_s=wall, messages=(_describe(status),))

    assignments = _extract(problem, built, solver)
    objective = round(solver.objective_value)
    _check(problem, assignments, objective, params.weighted, params.no_idle)

    if (
        status is SolveStatus.FEASIBLE
        and start is not None
        and objective_value(problem, start, weighted=params.weighted) < objective
    ):
        return _start_result(problem, start, params, wall, "the solver's schedule was worse")

    bound = solver.best_objective_bound
    return SolveResult(
        status=status,
        assignments=assignments,
        objective=objective,
        best_bound=bound,
        gap=abs(objective - bound) / max(1.0, abs(objective)),
        wall_time_s=wall,
    )


def _start_result(
    problem: ProblemInstance,
    schedule: tuple[Assignment, ...],
    params: SolveParams,
    wall: float,
    reason: str,
) -> SolveResult:
    """Return the verified start schedule as ``FEASIBLE`` (never ``OPTIMAL``, no bound known)."""
    objective = objective_value(problem, schedule, weighted=params.weighted)
    _check(problem, schedule, objective, params.weighted, params.no_idle)
    return SolveResult(
        status=SolveStatus.FEASIBLE,
        assignments=schedule,
        objective=objective,
        wall_time_s=wall,
        messages=(
            f"{reason} within the time limit; this is the verified start schedule from a "
            "simple dispatch rule. A longer time limit may find a better one.",
        ),
    )


def _add_start_hint(built: BuiltModel, schedule: tuple[Assignment, ...]) -> None:
    """Give the solver a valid starting schedule. A hint never changes what is feasible or
    optimal; it only lets the search start from a good solution."""
    used: dict[str, set[str]] = {}
    starts: dict[str, int] = {}
    for a in schedule:
        used.setdefault(a.job_id, set()).add(a.resource_id)
        starts[a.job_id] = a.start
    for job_id, start in starts.items():
        built.model.add_hint(built.starts[job_id], start)
        for option in built.options[job_id]:
            built.model.add_hint(option.literal, int(set(option.resource_ids) == used[job_id]))


def _extract(
    problem: ProblemInstance, built: BuiltModel, solver: cp_model.CpSolver
) -> tuple[Assignment, ...]:
    assignments: list[Assignment] = []
    for job in problem.jobs:
        start = solver.value(built.starts[job.id])
        chosen = [o for o in built.options[job.id] if solver.boolean_value(o.literal)]
        option = chosen[0]
        assignments.extend(
            Assignment(job.id, rid, start, start + option.duration) for rid in option.resource_ids
        )
    return tuple(assignments)


def _check(
    problem: ProblemInstance,
    assignments: tuple[Assignment, ...],
    objective: int,
    weighted: bool,
    no_idle: bool = False,
) -> None:
    violations = verify_schedule(problem, assignments, no_idle=no_idle)
    if violations:
        raise ScheduleVerificationError("; ".join(violations))
    recomputed = objective_value(problem, assignments, weighted=weighted)
    if recomputed != objective:
        raise ScheduleVerificationError(
            f"solver objective {objective} differs from recomputed objective {recomputed}"
        )


def _describe(status: SolveStatus) -> str:
    return {
        SolveStatus.INFEASIBLE: "proven infeasible: no schedule satisfies all constraints "
        "within the horizon",
        SolveStatus.UNKNOWN: "no feasible schedule found within the time limit",
        SolveStatus.MODEL_INVALID: "the solver rejected the model as invalid",
    }.get(status, status.value)
