"""A quick start schedule used as a hint for the solver (pure Python, no OR-Tools).

For the compute-farm case (every job has ``work``, can use every line, is released at 0, and
the lines are open for the whole horizon) running the jobs one after another, each on all lines
at once, is a valid schedule that never leaves a line idle. It is also a good schedule, because
merging every line finishes each job as early as possible. Two job orders are tried (earliest due
date first, and weighted shortest first) and the better one is returned.
"""

from __future__ import annotations

from itertools import combinations

from scheduler.engine.metrics import objective_value, verify_schedule
from scheduler.engine.models import Assignment, Job, ProblemInstance, Resource, duration_on


def sequential_merge_schedule(
    problem: ProblemInstance, *, weighted: bool = True
) -> tuple[Assignment, ...] | None:
    """The better of two sequential all-lines schedules, or ``None`` when not applicable."""
    if not _applicable(problem):
        return None
    resources = list(problem.resources)
    length = {job.id: duration_on(job, resources) for job in problem.jobs}

    orders = (
        sorted(problem.jobs, key=lambda j: (j.due, -j.priority, j.id)),
        sorted(problem.jobs, key=lambda j: (length[j.id] / j.priority, j.due, j.id)),
    )
    best: tuple[Assignment, ...] | None = None
    best_value: int | None = None
    for order in orders:
        schedule = _run_in_order(problem, order, length)
        if schedule is None:
            continue
        value = objective_value(problem, schedule, weighted=weighted)
        if best_value is None or value < best_value:
            best, best_value = schedule, value
    return best


def _applicable(problem: ProblemInstance) -> bool:
    ids = {r.id for r in problem.resources}
    total = sum(r.capacity for r in problem.resources)
    if problem.max_merge_capacity is not None and total > problem.max_merge_capacity:
        return False
    if not problem.jobs or any(
        j.work is None or j.release != 0 or j.after is not None or set(j.eligible) != ids
        for j in problem.jobs
    ):
        return False
    return all(
        len(r.windows) == 1 and r.windows[0].start == 0 and r.windows[0].end == problem.horizon
        for r in problem.resources
    )


def _run_in_order(
    problem: ProblemInstance, order: list[Job], length: dict[str, int]
) -> tuple[Assignment, ...] | None:
    rows: list[Assignment] = []
    clock = 0
    for job in order:
        end = clock + length[job.id]
        if end > problem.horizon:
            return None
        rows.extend(Assignment(job.id, r.id, clock, end) for r in problem.resources)
        clock = end
    return tuple(rows)


def best_start_schedule(
    problem: ProblemInstance, *, weighted: bool = True, no_idle: bool = False
) -> tuple[Assignment, ...] | None:
    """The best valid start schedule from the available heuristics, or ``None``."""
    candidates = [
        schedule
        for schedule in (
            sequential_merge_schedule(problem, weighted=weighted),
            dispatch_schedule(problem),
        )
        if schedule is not None and not verify_schedule(problem, schedule, no_idle=no_idle)
    ]
    return min(
        candidates, key=lambda s: objective_value(problem, s, weighted=weighted), default=None
    )


def dispatch_schedule(problem: ProblemInstance) -> tuple[Assignment, ...] | None:
    """A work-conserving list schedule (never leaves a line idle while a job can use it).

    Whenever a line is free and a job is available (released, and its ``after`` job has ended)
    the most urgent such job starts at once on the free lines it can use: jobs with a cycle limit
    first, then earliest due date. A job with ``work`` takes the free eligible lines with the
    largest total capacity that stays within the merge cap. Applies when every line is open from
    some time until the horizon with no gaps; otherwise ``None``.
    """
    if not problem.jobs or any(
        len(r.windows) != 1 or r.windows[0].end != problem.horizon for r in problem.resources
    ):
        return None
    resources = problem.resource_by_id()
    free_at = {r.id: r.windows[0].start for r in problem.resources}
    pending = {job.id: job for job in problem.jobs}
    finished: dict[str, int] = {}
    rows: list[Assignment] = []
    clock = min(free_at.values())

    while pending:
        started = True
        while started:
            started = False
            free = {rid for rid, at in free_at.items() if at <= clock}
            ready = sorted(
                (
                    job for job in pending.values()
                    if job.release <= clock
                    and (job.after is None or finished.get(job.after, clock + 1) <= clock)
                ),
                key=lambda j: (j.cycle_limit is None, j.due, -j.priority, j.id),
            )
            for job in ready:
                usable = [resources[rid] for rid in job.eligible if rid in free]
                chosen = _choose_lines(job, usable, problem.max_merge_capacity)
                if chosen is None:
                    continue
                end = clock + duration_on(job, chosen)
                if end > problem.horizon:
                    return None
                for resource in chosen:
                    rows.append(Assignment(job.id, resource.id, clock, end))
                    free_at[resource.id] = end
                finished[job.id] = end
                del pending[job.id]
                started = True
                break
        later = [at for at in free_at.values() if at > clock]
        later += [job.release for job in pending.values() if job.release > clock]
        later += [
            finished[job.after] for job in pending.values()
            if job.after in finished and finished[job.after] > clock
        ]
        if not later:
            return None
        clock = min(later)
    return tuple(rows)


def _choose_lines(
    job: Job, usable: list[Resource], max_capacity: int | None
) -> tuple[Resource, ...] | None:
    """Lines a job takes right now: one for a fixed-duration job, the largest allowed merge for
    a job with ``work``."""
    if not usable:
        return None
    if job.work is None:
        return (usable[0],)
    best: tuple[Resource, ...] | None = None
    best_key: tuple[int, int] | None = None
    for size in range(1, len(usable) + 1):
        for subset in combinations(usable, size):
            capacity = sum(r.capacity for r in subset)
            if max_capacity is not None and capacity > max_capacity:
                continue
            key = (capacity, -size)
            if best_key is None or key > best_key:
                best, best_key = subset, key
    return best
