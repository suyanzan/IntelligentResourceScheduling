"""CP-SAT model construction.

Formulation (all times are integer units, windows are half-open):

* ``x[j, r]``  boolean, job ``j`` runs on resource ``r`` (only for eligible ``r``).
* ``s_j``      start of job ``j``, in ``[release_j, horizon - p_j]``.
* ``I[j, r]``  optional interval ``[s_j, s_j + p_j)`` present iff ``x[j, r]``.
* ``T_j``      tardiness, ``T_j >= s_j + p_j - due_j`` and ``T_j >= 0``.

Constraints: each job on exactly one eligible resource; per resource a ``NoOverlap`` over its
optional intervals plus one fixed interval for every closed (unavailable) period. Because a job
is a single non-preemptive interval, it must then lie entirely inside one availability window.

Objective: minimize ``sum(w_j * T_j)`` (or plain total tardiness when ``weighted`` is false).
"""

from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from scheduler.engine.models import Job, ProblemInstance, Resource


@dataclass(slots=True)
class BuiltModel:
    """A CP-SAT model together with the variables needed to read a solution back."""

    model: cp_model.CpModel
    starts: dict[str, cp_model.IntVar]
    presence: dict[tuple[str, str], cp_model.IntVar]


def blocked_periods(resource: Resource, horizon: int) -> list[tuple[int, int]]:
    """Closed periods of ``resource`` inside ``[0, horizon)`` as ``(start, end)`` pairs."""
    windows = sorted(
        (max(0, w.start), min(horizon, w.end))
        for w in resource.windows
        if w.end > w.start and w.end > 0 and w.start < horizon
    )
    blocked: list[tuple[int, int]] = []
    cursor = 0
    for start, end in windows:
        if start > cursor:
            blocked.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < horizon:
        blocked.append((cursor, horizon))
    return blocked


def build_model(problem: ProblemInstance, *, weighted: bool = True) -> BuiltModel:
    """Build the CP-SAT model for a validated problem instance."""
    model = cp_model.CpModel()
    horizon = problem.horizon

    starts: dict[str, cp_model.IntVar] = {}
    presence: dict[tuple[str, str], cp_model.IntVar] = {}
    intervals_by_resource: dict[str, list[cp_model.IntervalVar]] = {
        r.id: [] for r in problem.resources
    }
    tardiness_terms: list[cp_model.LinearExpr] = []

    for job in problem.jobs:
        _add_job(model, job, horizon, weighted, starts, presence, intervals_by_resource,
                 tardiness_terms)

    for resource in problem.resources:
        fixed = [
            model.new_fixed_size_interval_var(start, end - start, f"closed_{resource.id}_{start}")
            for start, end in blocked_periods(resource, horizon)
        ]
        model.add_no_overlap([*intervals_by_resource[resource.id], *fixed])

    model.minimize(sum(tardiness_terms))
    return BuiltModel(model=model, starts=starts, presence=presence)


def _add_job(
    model: cp_model.CpModel,
    job: Job,
    horizon: int,
    weighted: bool,
    starts: dict[str, cp_model.IntVar],
    presence: dict[tuple[str, str], cp_model.IntVar],
    intervals_by_resource: dict[str, list[cp_model.IntervalVar]],
    tardiness_terms: list[cp_model.LinearExpr],
) -> None:
    start = model.new_int_var(job.release, horizon - job.duration, f"start_{job.id}")
    starts[job.id] = start

    literals: list[cp_model.IntVar] = []
    for resource_id in job.eligible:
        literal = model.new_bool_var(f"on_{job.id}_{resource_id}")
        presence[(job.id, resource_id)] = literal
        literals.append(literal)
        interval = model.new_optional_interval_var(
            start, job.duration, start + job.duration, literal, f"iv_{job.id}_{resource_id}"
        )
        intervals_by_resource[resource_id].append(interval)
    model.add_exactly_one(literals)

    late = model.new_int_var(0, horizon, f"late_{job.id}")
    model.add(late >= start + job.duration - job.due)
    tardiness_terms.append((job.priority if weighted else 1) * late)
