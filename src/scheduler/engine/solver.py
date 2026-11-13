"""Solver wrapper: validation, CP-SAT solve, status mapping and result verification.

``OPTIMAL`` is only reported when CP-SAT proves optimality. Every returned schedule is re-checked
by :func:`scheduler.engine.metrics.verify_schedule` and its objective is recomputed independently;
a disagreement raises :class:`ScheduleVerificationError` instead of returning a wrong answer.
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from scheduler.engine.cpsat_model import BuiltModel, build_model
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


def map_status(cp_status: int) -> SolveStatus:
    """Map a CP-SAT status code to :class:`SolveStatus` (never upgrades FEASIBLE)."""
    mapping: dict[int, SolveStatus] = {
        int(cp_model.OPTIMAL): SolveStatus.OPTIMAL,
        int(cp_model.FEASIBLE): SolveStatus.FEASIBLE,
        int(cp_model.INFEASIBLE): SolveStatus.INFEASIBLE,
        int(cp_model.MODEL_INVALID): SolveStatus.MODEL_INVALID,
    }
    return mapping.get(int(cp_status), SolveStatus.UNKNOWN)


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

    issues = [*validate_instance(problem), *validate_params(params)]
    if issues:
        return SolveResult(status=SolveStatus.MODEL_INVALID, messages=tuple(issues))

    built = build_model(problem, weighted=params.weighted)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = params.time_limit_s
    solver.parameters.num_workers = params.num_workers
    solver.parameters.random_seed = params.random_seed

    status = map_status(solver.solve(built.model))
    wall = solver.wall_time

    if status in (SolveStatus.INFEASIBLE, SolveStatus.UNKNOWN, SolveStatus.MODEL_INVALID):
        return SolveResult(status=status, wall_time_s=wall, messages=(_describe(status),))

    assignments = _extract(problem, built, solver)
    objective = round(solver.objective_value)
    _check(problem, assignments, objective, params.weighted)

    bound = solver.best_objective_bound
    return SolveResult(
        status=status,
        assignments=assignments,
        objective=objective,
        best_bound=bound,
        gap=abs(objective - bound) / max(1.0, abs(objective)),
        wall_time_s=wall,
    )


def _extract(
    problem: ProblemInstance, built: BuiltModel, solver: cp_model.CpSolver
) -> tuple[Assignment, ...]:
    assignments: list[Assignment] = []
    for job in problem.jobs:
        start = solver.value(built.starts[job.id])
        chosen = [
            rid for rid in job.eligible if solver.boolean_value(built.presence[(job.id, rid)])
        ]
        assignments.append(Assignment(job.id, chosen[0], start, start + job.duration))
    return tuple(assignments)


def _check(
    problem: ProblemInstance,
    assignments: tuple[Assignment, ...],
    objective: int,
    weighted: bool,
) -> None:
    violations = verify_schedule(problem, assignments)
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
