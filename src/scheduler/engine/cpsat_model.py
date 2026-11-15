"""CP-SAT model construction.

Formulation (all times are integer units, windows are half-open):

* ``x[j, o]``  boolean, job ``j`` uses option ``o``. An option is a set of eligible resources
  that run the job together (a classic job has one single-resource option per eligible
  resource; a job with ``work`` has one option per non-empty subset of its eligible resources)
  and a duration ``p_{j,o}`` (fixed, or ``ceil(work / total capacity)``).
* ``s_j``      start of job ``j``, in ``[release_j, horizon)``.
* ``e_j``      end of job ``j``; ``e_j = s_j + p_{j,o}`` when option ``o`` is chosen.
* ``I[j,o,r]`` optional interval ``[s_j, s_j + p_{j,o})`` on resource ``r`` of option ``o``,
  present iff ``x[j, o]``.
* ``T_j``      tardiness, ``T_j >= e_j - due_j`` and ``T_j >= 0``.

Constraints: each job picks exactly one option; per resource a ``NoOverlap`` over its optional
intervals plus one fixed interval for every closed (unavailable) period. Because a job is a
single non-preemptive interval on each chosen resource, it must then lie entirely inside one
availability window of each of them.

Objective: minimize ``sum(w_j * T_j)`` (or plain total tardiness when ``weighted`` is false).
"""

from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from scheduler.engine.models import Job, ProblemInstance, Resource, duration_on, option_sets


@dataclass(frozen=True, slots=True)
class Option:
    """One way to run a job: a set of resources used together and the resulting duration."""

    resource_ids: tuple[str, ...]
    duration: int
    literal: cp_model.IntVar


@dataclass(slots=True)
class BuiltModel:
    """A CP-SAT model together with the variables needed to read a solution back."""

    model: cp_model.CpModel
    starts: dict[str, cp_model.IntVar]
    options: dict[str, list[Option]]


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
    resources = problem.resource_by_id()

    starts: dict[str, cp_model.IntVar] = {}
    options: dict[str, list[Option]] = {}
    intervals_by_resource: dict[str, list[cp_model.IntervalVar]] = {
        r.id: [] for r in problem.resources
    }
    tardiness_terms: list[cp_model.LinearExpr] = []

    for job in problem.jobs:
        _add_job(
            model, job, resources, horizon, weighted, starts, options,
            intervals_by_resource, tardiness_terms,
        )

    for resource in problem.resources:
        fixed = [
            model.new_fixed_size_interval_var(start, end - start, f"closed_{resource.id}_{start}")
            for start, end in blocked_periods(resource, horizon)
        ]
        model.add_no_overlap([*intervals_by_resource[resource.id], *fixed])

    model.minimize(sum(tardiness_terms))
    return BuiltModel(model=model, starts=starts, options=options)


def _add_job(
    model: cp_model.CpModel,
    job: Job,
    resources: dict[str, Resource],
    horizon: int,
    weighted: bool,
    starts: dict[str, cp_model.IntVar],
    options: dict[str, list[Option]],
    intervals_by_resource: dict[str, list[cp_model.IntervalVar]],
    tardiness_terms: list[cp_model.LinearExpr],
) -> None:
    start = model.new_int_var(job.release, horizon, f"start_{job.id}")
    end = model.new_int_var(job.release, horizon, f"end_{job.id}")
    starts[job.id] = start

    chosen: list[Option] = []
    for subset in option_sets(job, resources):
        duration = duration_on(job, subset)
        if job.release + duration > horizon:
            continue  # this combination can never finish inside the horizon
        ids = tuple(resource.id for resource in subset)
        label = f"{job.id}_{'+'.join(ids)}"
        literal = model.new_bool_var(f"use_{label}")
        chosen.append(Option(ids, duration, literal))
        model.add(end == start + duration).only_enforce_if(literal)
        for rid in ids:
            interval = model.new_optional_interval_var(
                start, duration, start + duration, literal, f"iv_{label}_{rid}"
            )
            intervals_by_resource[rid].append(interval)
    options[job.id] = chosen
    model.add_exactly_one([option.literal for option in chosen])

    late = model.new_int_var(0, horizon, f"late_{job.id}")
    model.add(late >= end - job.due)
    tardiness_terms.append((job.priority if weighted else 1) * late)
