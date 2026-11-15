"""Engine data models.

Conventions:

* Time is discrete: every time value is an integer number of time units counted from 0.
* Windows are half-open intervals ``[start, end)``.
* A job is non-preemptive. A classic job uses exactly one resource for a fixed ``duration``.
* A job with ``work`` (capacity-hours, e.g. CPU-hours) may use several of its eligible resources
  at once ("merging"): all chosen resources start and end together, each handles only that job
  while it runs, and the duration is ``ceil(work / total capacity of the chosen resources)``.
* ``priority`` is 1..5 (higher means more important) and doubles as the tardiness weight.
* Delay of a job is ``end - due`` (negative when early); tardiness is ``max(0, delay)`` and a job
  is on time when its tardiness is 0.
* A job may wait for another (``after``): it cannot start before that job has ended.
* A job may have a ``cycle_limit`` (units from its release to its end). Going over it is not
  forbidden: it costs one "cycle point", and each point adds ``cycle_penalty`` to the objective.
* ``max_merge_capacity`` caps the combined capacity of the resources one job may merge.

The models are plain, permissive dataclasses: structural problems (bad durations, overlapping
windows, ...) are reported by :mod:`scheduler.engine.validation` rather than raised here, so
callers can collect every problem at once.

This module imports only the standard library so the engine stays independent of FastAPI,
SQLAlchemy and Pydantic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations


class SolveStatus(StrEnum):
    """Solver outcome. Only ``OPTIMAL`` means optimality was proven."""

    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"
    MODEL_INVALID = "MODEL_INVALID"


@dataclass(frozen=True, slots=True)
class Window:
    """A half-open availability interval ``[start, end)`` in time units."""

    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class Resource:
    """A resource that processes one job at a time, only inside its windows."""

    id: str
    name: str
    windows: tuple[Window, ...]
    capacity: int = 1  # processing capacity per time unit (e.g. CPUs); used by jobs with work


@dataclass(frozen=True, slots=True)
class Job:
    """A non-preemptive job needing exactly one eligible resource."""

    id: str
    name: str
    duration: int
    due: int
    eligible: tuple[str, ...]
    priority: int = 1
    release: int = 0
    work: int | None = None  # capacity-hours; when set, ``duration`` is ignored
    after: str | None = None  # id of a job that must end before this one starts
    cycle_limit: int | None = None  # max units from release to end before a cycle point is given
    layer: str = ""  # free-text label, e.g. "DIFFUSION" (display only)


def duration_on(job: Job, resources: Sequence[Resource]) -> int:
    """Duration of ``job`` when it runs on all of ``resources`` together.

    Classic jobs return their fixed duration. Jobs with ``work`` return
    ``ceil(work / total capacity)``.
    """
    if job.work is None:
        return job.duration
    total = sum(resource.capacity for resource in resources)
    return -(-job.work // total)


def option_sets(
    job: Job, resources: dict[str, Resource], max_capacity: int | None = None
) -> list[tuple[Resource, ...]]:
    """Resource sets a job may use: one per eligible resource, or every non-empty subset when
    the job has ``work`` (so it may merge resources). With ``max_capacity`` a merged set whose
    total capacity is larger is not allowed."""
    eligible = [resources[rid] for rid in job.eligible]
    if job.work is None:
        return [(resource,) for resource in eligible]
    subsets = (
        subset
        for size in range(1, len(eligible) + 1)
        for subset in combinations(eligible, size)
    )
    return [
        subset
        for subset in subsets
        if max_capacity is None or sum(r.capacity for r in subset) <= max_capacity
    ]


def over_cycle(job: Job, end: int) -> bool:
    """True when ``job`` has a cycle limit and ending at ``end`` exceeds it."""
    return job.cycle_limit is not None and end - job.release > job.cycle_limit


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


@dataclass(frozen=True, slots=True)
class ProblemInstance:
    """A complete scheduling problem over the horizon ``[0, horizon)``."""

    horizon: int
    resources: tuple[Resource, ...]
    jobs: tuple[Job, ...]
    max_merge_capacity: int | None = None  # cap on the total capacity of merged resources
    cycle_penalty: int = 50  # objective cost of one cycle point

    def job_by_id(self) -> dict[str, Job]:
        return {job.id: job for job in self.jobs}

    def resource_by_id(self) -> dict[str, Resource]:
        return {resource.id: resource for resource in self.resources}


@dataclass(frozen=True, slots=True)
class Assignment:
    """A job placed on a resource during ``[start, end)``.

    A job that merges several resources has one assignment per resource, all with the same
    start and end.
    """

    job_id: str
    resource_id: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SolveParams:
    """Solver settings. Defaults favour reproducibility (single worker, fixed seed)."""

    time_limit_s: float = 30.0
    num_workers: int = 1
    random_seed: int = 0
    weighted: bool = True
    # Rule: a resource may not sit idle while a job it can run has not started yet. It may idle
    # only after every job it could run has started. Needs every job's release time to be 0.
    no_idle: bool = False


@dataclass(frozen=True, slots=True)
class SolveResult:
    """Result of a solve: status, schedule and solver statistics."""

    status: SolveStatus
    assignments: tuple[Assignment, ...] = ()
    objective: int | None = None
    best_bound: float | None = None
    gap: float | None = None
    wall_time_s: float = 0.0
    messages: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Metrics:
    """Schedule quality metrics computed independently of the solver."""

    job_count: int
    on_time_count: int
    on_time_rate: float
    total_tardiness: int
    weighted_tardiness: int
    makespan: int
    utilization: dict[str, float]
    mean_delay: float = 0.0  # sum of positive delays / number of jobs (early jobs count as 0)
    cycle_points: int = 0  # jobs that exceeded their cycle limit
