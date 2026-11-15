"""Schedule metrics and an independent schedule verifier.

Nothing here depends on the solver. The verifier re-checks a schedule against the problem from
scratch, and the metric functions recompute tardiness from the assignments, so solver output can
be cross-checked rather than trusted.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Literal

from scheduler.engine.models import (
    Assignment,
    Job,
    Metrics,
    ProblemInstance,
    Window,
    duration_on,
)

UtilizationBasis = Literal["makespan", "horizon"]


def delay(job: Job, end: int) -> int:
    """Signed delay of a job finishing at ``end``: ``end - due`` (negative when early)."""
    return end - job.due


def tardiness(job: Job, end: int) -> int:
    """Tardiness of a job finishing at ``end``: ``max(0, end - due)``."""
    return max(0, delay(job, end))


def job_ends(assignments: Sequence[Assignment]) -> dict[str, int]:
    """End time per job. A job that merges several resources has several assignments that share
    one end time, so each job is counted once."""
    return {a.job_id: a.end for a in assignments}


def job_delays(problem: ProblemInstance, assignments: Sequence[Assignment]) -> dict[str, int]:
    """Signed delay (``end - due``) for every assigned job."""
    jobs = problem.job_by_id()
    return {
        job_id: delay(_lookup_job(jobs, job_id), end)
        for job_id, end in job_ends(assignments).items()
    }


def objective_value(
    problem: ProblemInstance,
    assignments: Sequence[Assignment],
    *,
    weighted: bool = True,
) -> int:
    """Total (optionally priority-weighted) tardiness of a schedule."""
    jobs = problem.job_by_id()
    total = 0
    for job_id, end in job_ends(assignments).items():
        job = _lookup_job(jobs, job_id)
        late = tardiness(job, end)
        total += late * job.priority if weighted else late
    return total


def available_units(windows: Sequence[Window], upto: int) -> int:
    """Number of calendar units inside ``windows`` over ``[0, upto)``."""
    return sum(max(0, min(w.end, upto) - max(w.start, 0)) for w in windows)


def daily_capacity(windows: Sequence[Window], units_per_day: int) -> int:
    """Largest number of available units on any single day (windows split at day boundaries)."""
    if units_per_day < 1:
        raise ValueError("units_per_day must be at least 1")
    per_day: dict[int, int] = defaultdict(int)
    for window in windows:
        cursor = window.start
        while cursor < window.end:
            day = cursor // units_per_day
            segment_end = min(window.end, (day + 1) * units_per_day)
            per_day[day] += segment_end - cursor
            cursor = segment_end
    return max(per_day.values(), default=0)


def compute_metrics(
    problem: ProblemInstance,
    assignments: Sequence[Assignment],
    *,
    utilization_basis: UtilizationBasis = "makespan",
) -> Metrics:
    """Compute schedule metrics.

    Utilization is busy units divided by available calendar units, measured over
    ``[0, makespan)`` by default or over the whole horizon with ``utilization_basis="horizon"``.
    A resource with no available units in the measured range reports 0.0. With no jobs the
    on-time rate is 1.0.
    """
    jobs = problem.job_by_id()
    on_time = 0
    total_late = 0
    weighted_late = 0
    makespan = 0
    busy: dict[str, int] = defaultdict(int)

    ends = job_ends(assignments)
    for job_id, end in ends.items():
        job = _lookup_job(jobs, job_id)
        late = tardiness(job, end)
        total_late += late
        weighted_late += late * job.priority
        if late == 0:
            on_time += 1
    for assignment in assignments:
        makespan = max(makespan, assignment.end)
        busy[assignment.resource_id] += assignment.end - assignment.start

    upto = makespan if utilization_basis == "makespan" else problem.horizon
    utilization: dict[str, float] = {}
    for resource in problem.resources:
        available = available_units(resource.windows, upto)
        utilization[resource.id] = busy[resource.id] / available if available > 0 else 0.0

    job_count = len(ends)
    return Metrics(
        job_count=job_count,
        on_time_count=on_time,
        on_time_rate=on_time / job_count if job_count else 1.0,
        total_tardiness=total_late,
        weighted_tardiness=weighted_late,
        makespan=makespan,
        utilization=utilization,
        mean_delay=total_late / job_count if job_count else 0.0,
    )


def verify_schedule(problem: ProblemInstance, assignments: Sequence[Assignment]) -> list[str]:
    """Check a schedule against the problem; an empty list means it is valid.

    Checks: every job placed, known job and resources, eligibility, one shared start and end for
    all resources of a job, the right duration (fixed, or ``ceil(work / total capacity)``),
    release time, horizon, containment in a single availability window of every used resource,
    and no overlap on a resource.
    """
    violations: list[str] = []
    jobs = problem.job_by_id()
    resources = problem.resource_by_id()

    rows: dict[str, list[Assignment]] = defaultdict(list)
    for a in assignments:
        rows[a.job_id].append(a)
    for job_id in rows:
        if job_id not in jobs:
            violations.append(f"assignment refers to unknown job {job_id!r}")
    for job_id in jobs:
        if job_id not in rows:
            violations.append(f"job {job_id!r} has no assignment")

    by_resource: dict[str, list[Assignment]] = defaultdict(list)
    for job_id, items in rows.items():
        job = jobs.get(job_id)
        used: list[str] = []
        for a in items:
            if a.resource_id in used:
                violations.append(f"job {job_id!r} uses resource {a.resource_id!r} more than once")
            used.append(a.resource_id)
            if a.resource_id not in resources:
                violations.append(f"job {job_id!r} uses unknown resource {a.resource_id!r}")
                continue
            by_resource[a.resource_id].append(a)
        if job is None:
            continue
        violations.extend(_verify_job(problem, job, items))

    for resource_id, items in by_resource.items():
        ordered = sorted(items, key=lambda x: (x.start, x.end))
        for prev, cur in zip(ordered, ordered[1:], strict=False):
            if cur.start < prev.end:
                violations.append(
                    f"jobs {prev.job_id!r} and {cur.job_id!r} overlap on resource {resource_id!r}"
                )

    return violations


def _verify_job(problem: ProblemInstance, job: Job, items: list[Assignment]) -> list[str]:
    violations: list[str] = []
    resources = problem.resource_by_id()
    first = items[0]

    if any((a.start, a.end) != (first.start, first.end) for a in items):
        violations.append(f"job {job.id!r} resources do not share one start and end")
    if job.work is None and len(items) > 1:
        violations.append(f"job {job.id!r} has a fixed duration and cannot merge resources")

    used = [resources[a.resource_id] for a in items if a.resource_id in resources]
    for a in items:
        if a.resource_id not in job.eligible:
            violations.append(f"job {job.id!r} is not eligible for resource {a.resource_id!r}")

    expected = duration_on(job, used) if used else None
    if expected is not None and first.end - first.start != expected:
        violations.append(
            f"job {job.id!r} spans {first.end - first.start} units but its duration is "
            f"{expected}"
        )
    if first.start < job.release:
        violations.append(
            f"job {job.id!r} starts at {first.start}, before its release time {job.release}"
        )
    if first.start < 0 or first.end > problem.horizon:
        violations.append(
            f"job {job.id!r} [{first.start}, {first.end}) is beyond the horizon "
            f"[0, {problem.horizon})"
        )
    for a in items:
        resource = resources.get(a.resource_id)
        if resource is not None and not any(
            w.start <= a.start and a.end <= w.end for w in resource.windows
        ):
            violations.append(
                f"job {job.id!r} [{a.start}, {a.end}) is not inside a single availability "
                f"window of resource {a.resource_id!r}"
            )
    return violations


def _lookup_job(jobs: dict[str, Job], job_id: str) -> Job:
    try:
        return jobs[job_id]
    except KeyError:
        raise ValueError(f"unknown job id {job_id!r}") from None
