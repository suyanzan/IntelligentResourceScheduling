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
* ``C_j``      cycle point (only for jobs with a cycle limit): ``C_j`` is 1 unless
  ``e_j - release_j <= cycle_limit_j``.

A job with ``after`` starts no earlier than the end of that job.

Constraints: each job picks exactly one option; per resource a ``NoOverlap`` over its optional
intervals plus one fixed interval for every closed (unavailable) period. Because a job is a
single non-preemptive interval on each chosen resource, it must then lie entirely inside one
availability window of each of them.

Objective: minimize ``sum(w_j * T_j) + cycle_penalty * sum(C_j)`` (plain total tardiness when
``weighted`` is false). ``max_merge_capacity`` removes merged options that are too large.
"""

from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from scheduler.engine.models import (
    Job,
    ProblemInstance,
    Resource,
    blocked_periods,
    duration_on,
    option_sets,
)

__all__ = ["BuiltModel", "Option", "blocked_periods", "build_model"]


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
    ends: dict[str, cp_model.IntVar]
    options: dict[str, list[Option]]


def build_model(
    problem: ProblemInstance, *, weighted: bool = True, no_idle: bool = False
) -> BuiltModel:
    """Build the CP-SAT model for a validated problem instance.

    With ``no_idle`` a resource must stay busy (or closed) from time 0 until the last job it
    could run has started; see :func:`_add_no_idle`.
    """
    model = cp_model.CpModel()
    horizon = problem.horizon
    resources = problem.resource_by_id()

    starts: dict[str, cp_model.IntVar] = {}
    ends: dict[str, cp_model.IntVar] = {}
    options: dict[str, list[Option]] = {}
    intervals_by_resource: dict[str, list[cp_model.IntervalVar]] = {
        r.id: [] for r in problem.resources
    }
    tardiness_terms: list[cp_model.LinearExpr] = []

    for job in problem.jobs:
        _add_job(
            model, job, resources, horizon, weighted, starts, ends, options,
            intervals_by_resource, tardiness_terms, problem.max_merge_capacity,
            problem.cycle_penalty,
        )
    for job in problem.jobs:
        if job.after is not None:
            model.add(starts[job.id] >= ends[job.after])

    for resource in problem.resources:
        fixed = [
            model.new_fixed_size_interval_var(start, end - start, f"closed_{resource.id}_{start}")
            for start, end in blocked_periods(resource, horizon)
        ]
        model.add_no_overlap([*intervals_by_resource[resource.id], *fixed])

    if no_idle:
        _add_no_idle(model, problem, starts, ends, options)

    model.minimize(sum(tardiness_terms))
    return BuiltModel(model=model, starts=starts, ends=ends, options=options)


def _add_job(
    model: cp_model.CpModel,
    job: Job,
    resources: dict[str, Resource],
    horizon: int,
    weighted: bool,
    starts: dict[str, cp_model.IntVar],
    ends: dict[str, cp_model.IntVar],
    options: dict[str, list[Option]],
    intervals_by_resource: dict[str, list[cp_model.IntervalVar]],
    tardiness_terms: list[cp_model.LinearExpr],
    max_capacity: int | None,
    cycle_penalty: int,
) -> None:
    start = model.new_int_var(job.release, horizon, f"start_{job.id}")
    end = model.new_int_var(job.release, horizon, f"end_{job.id}")
    starts[job.id] = start
    ends[job.id] = end

    chosen: list[Option] = []
    for subset in option_sets(job, resources, max_capacity):
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

    if job.cycle_limit is not None:
        over = model.new_bool_var(f"over_cycle_{job.id}")
        model.add(end - job.release <= job.cycle_limit).only_enforce_if(over.negated())
        tardiness_terms.append(cycle_penalty * over)


def _add_no_idle(
    model: cp_model.CpModel,
    problem: ProblemInstance,
    starts: dict[str, cp_model.IntVar],
    ends: dict[str, cp_model.IntVar],
    options: dict[str, list[Option]],
) -> None:
    """While a job waits, every resource it could use must be busy or closed.

    Job ``j`` waits during ``[a_j, s_j)`` where ``a_j`` is its release time or the end of the job
    it comes ``after`` (whichever is later). For each resource ``r`` that ``j`` is eligible for,
    the time inside that window that ``r`` spends on other jobs, plus its closed periods inside
    the window, must add up to the whole window. Intervals on one resource never overlap, so the
    sum equals the window length exactly when ``r`` has no gap there.
    """
    horizon = problem.horizon
    resources = problem.resource_by_id()

    avail: dict[str, cp_model.IntVar | int] = {}
    for job in problem.jobs:
        if job.after is None:
            avail[job.id] = job.release
        else:
            var = model.new_int_var(job.release, horizon, f"avail_{job.id}")
            model.add_max_equality(var, [ends[job.after], job.release])
            avail[job.id] = var

    uses: dict[tuple[str, str], cp_model.IntVar] = {}
    for job in problem.jobs:
        for rid in job.eligible:
            literals = [o.literal for o in options[job.id] if rid in o.resource_ids]
            if not literals:
                continue
            if len(literals) == 1:
                uses[(job.id, rid)] = literals[0]
            else:
                used = model.new_bool_var(f"uses_{job.id}_{rid}")
                model.add(used == cp_model.LinearExpr.sum(literals))
                uses[(job.id, rid)] = used

    def overlap(
        low: cp_model.IntVar | int, high: cp_model.IntVar | int,
        start: cp_model.IntVar | int, end: cp_model.IntVar | int, name: str,
    ) -> cp_model.IntVar:
        """Length of ``[low, high)`` that lies inside ``[start, end)``."""
        left = model.new_int_var(0, horizon, f"l_{name}")
        model.add_max_equality(left, [low, start])
        right = model.new_int_var(0, horizon, f"r_{name}")
        model.add_min_equality(right, [high, end])
        gap = model.new_int_var(-horizon, horizon, f"g_{name}")
        model.add(gap == right - left)
        length = model.new_int_var(0, horizon, f"o_{name}")
        model.add_max_equality(length, [gap, 0])
        return length

    pair_overlap: dict[tuple[str, str], cp_model.IntVar] = {}
    for job in problem.jobs:
        waiting_from = avail[job.id]
        for other in problem.jobs:
            if other.id == job.id or other.after == job.id:
                continue  # a job that comes after ``job`` cannot run while ``job`` waits
            if not any((other.id, rid) in uses for rid in job.eligible):
                continue
            pair_overlap[(job.id, other.id)] = overlap(
                starts[other.id], ends[other.id], waiting_from, starts[job.id],
                f"{job.id}_{other.id}",
            )

    for job in problem.jobs:
        window = starts[job.id] - avail[job.id]
        for rid in job.eligible:
            covered: list[cp_model.IntVar] = []
            for other in problem.jobs:
                literal = uses.get((other.id, rid))
                pair = pair_overlap.get((job.id, other.id))
                if literal is None or pair is None:
                    continue
                part = model.new_int_var(0, horizon, f"cov_{job.id}_{other.id}_{rid}")
                model.add(part == pair).only_enforce_if(literal)
                model.add(part == 0).only_enforce_if(literal.negated())
                covered.append(part)
            for block_start, block_end in blocked_periods(resources[rid], horizon):
                covered.append(
                    overlap(
                        block_start, block_end, avail[job.id], starts[job.id],
                        f"{job.id}_{rid}_{block_start}",
                    )
                )
            model.add(cp_model.LinearExpr.sum(covered) == window)
