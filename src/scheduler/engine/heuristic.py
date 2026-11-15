"""A quick start schedule used as a hint for the solver (pure Python, no OR-Tools).

For the compute-farm case (every job has ``work``, can use every line, is released at 0, and
the lines are open for the whole horizon) running the jobs one after another, each on all lines
at once, is a valid schedule that never leaves a line idle. It is also a good schedule, because
merging every line finishes each job as early as possible. Two job orders are tried (earliest due
date first, and weighted shortest first) and the better one is returned.
"""

from __future__ import annotations

from scheduler.engine.metrics import objective_value
from scheduler.engine.models import Assignment, Job, ProblemInstance, duration_on


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
