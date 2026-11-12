"""Pre-solve validation of a :class:`ProblemInstance`.

Validation returns human-readable issues instead of raising, so a caller (and eventually the
API) can report every problem at once and answer ``MODEL_INVALID`` with a precise reason rather
than a bare ``INFEASIBLE``.
"""

from __future__ import annotations

from collections import Counter

from scheduler.engine.models import Job, ProblemInstance, Resource

MIN_PRIORITY = 1
MAX_PRIORITY = 5


def validate_instance(problem: ProblemInstance) -> list[str]:
    """Return a list of problems; an empty list means the instance is well formed."""
    issues: list[str] = []

    if problem.horizon <= 0:
        issues.append(f"horizon must be positive, got {problem.horizon}")

    issues.extend(_duplicate_ids("resource", [r.id for r in problem.resources]))
    issues.extend(_duplicate_ids("job", [j.id for j in problem.jobs]))

    for resource in problem.resources:
        issues.extend(_validate_windows(resource, problem.horizon))

    known_resources = {r.id: r for r in problem.resources}
    for job in problem.jobs:
        issues.extend(_validate_job(job, problem.horizon, known_resources))

    return issues


def _duplicate_ids(kind: str, ids: list[str]) -> list[str]:
    return [f"duplicate {kind} id {value!r}" for value, n in Counter(ids).items() if n > 1]


def _validate_windows(resource: Resource, horizon: int) -> list[str]:
    issues: list[str] = []
    valid: list[tuple[int, int]] = []
    for window in resource.windows:
        label = f"resource {resource.id!r} window [{window.start}, {window.end})"
        if window.end <= window.start:
            issues.append(f"{label} is empty or reversed")
        elif window.start < 0 or window.end > horizon:
            issues.append(f"{label} lies outside the horizon [0, {horizon})")
        else:
            valid.append((window.start, window.end))

    valid.sort()
    for (_, prev_end), (start, end) in zip(valid, valid[1:], strict=False):
        if start < prev_end:
            issues.append(
                f"resource {resource.id!r} has overlapping windows "
                f"(one ends at {prev_end}, the next starts at {start}, ends at {end})"
            )
    return issues


def _validate_job(job: Job, horizon: int, resources: dict[str, Resource]) -> list[str]:
    issues: list[str] = []
    label = f"job {job.id!r}"

    if job.duration <= 0:
        issues.append(f"{label} duration must be positive, got {job.duration}")
    if not MIN_PRIORITY <= job.priority <= MAX_PRIORITY:
        issues.append(
            f"{label} priority must be between {MIN_PRIORITY} and {MAX_PRIORITY}, "
            f"got {job.priority}"
        )
    if job.release < 0:
        issues.append(f"{label} release must be non-negative, got {job.release}")
    if job.due < 0:
        issues.append(f"{label} due date must be non-negative, got {job.due}")

    if not job.eligible:
        issues.append(f"{label} has no eligible resources")
        return issues

    unknown = [rid for rid in job.eligible if rid not in resources]
    for rid in unknown:
        issues.append(f"{label} lists unknown resource {rid!r}")

    known = [resources[rid] for rid in job.eligible if rid in resources]
    if known and job.duration > 0 and job.release >= 0 and not _fits_somewhere(job, known, horizon):
        issues.append(
            f"{label} (duration {job.duration}, release {job.release}) cannot fit in any "
            f"availability window of its eligible resources within the horizon"
        )
    return issues


def _fits_somewhere(job: Job, resources: list[Resource], horizon: int) -> bool:
    for resource in resources:
        for window in resource.windows:
            earliest = max(window.start, job.release)
            latest_end = min(window.end, horizon)
            if window.end > window.start and earliest + job.duration <= latest_end:
                return True
    return False
