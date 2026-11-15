"""Pure rules for re-planning what is left of a plan from what really happened.

Finished orders drop out. A running order keeps its lines busy until it is expected to end, and
its follow-up cannot start before then. Everything not started is scheduled again from "now".
The result is a new instance on the same time axis (same start date and unit), so planned and
actual times stay comparable with the original plan.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from dataclasses import dataclass

from scheduler.engine.models import Job, ProblemInstance, Resource, Window


class ReplanError(ValueError):
    """The remaining work cannot be turned into a valid instance."""


@dataclass(frozen=True, slots=True)
class Progress:
    """What the floor reports for one job of the plan."""

    status: str  # planned, running or done
    start_unit: float | None = None  # actual start, in (fractional) time units
    planned_units: int = 0  # planned length, used to guess when a running job ends
    lines: tuple[str, ...] = ()  # lines the job holds while it runs


def expected_end(progress: Progress, now_unit: int) -> int:
    """When a running order is expected to finish: its planned length, but never in the past."""
    start = progress.start_unit if progress.start_unit is not None else now_unit
    end = math.ceil(start + progress.planned_units)
    return end if end > now_unit else now_unit + 1


def remaining_problem(
    problem: ProblemInstance, progress: Mapping[str, Progress], now_unit: int
) -> ProblemInstance:
    """The instance for the work that is still to do at ``now_unit``."""
    if not 0 <= now_unit < problem.horizon:
        raise ReplanError("the planning horizon has ended; there is nothing left to plan in it")

    free_from: dict[str, int] = {}
    running_end: dict[str, int] = {}
    for code, state in progress.items():
        if state.status != "running":
            continue
        end = expected_end(state, now_unit)
        running_end[code] = end
        for line in state.lines:
            free_from[line] = max(free_from.get(line, now_unit), end)

    resources: list[Resource] = []
    for resource in problem.resources:
        start_at = free_from.get(resource.id, now_unit)
        windows = tuple(
            Window(max(w.start, start_at), w.end) for w in resource.windows if w.end > start_at
        )
        if windows:
            resources.append(dataclasses.replace(resource, windows=windows))
    if not resources:
        raise ReplanError("no line is available any more within the planning horizon")
    kept = {r.id for r in resources}

    open_codes = {
        job.id
        for job in problem.jobs
        if progress.get(job.id, Progress("planned")).status == "planned"
    }
    if not open_codes:
        raise ReplanError("every order is finished or running; there is nothing left to plan")

    jobs: list[Job] = []
    for job in problem.jobs:
        if job.id not in open_codes:
            continue
        release = max(job.release, now_unit)
        after = job.after
        if after is not None and after not in open_codes:
            if after in running_end:
                release = max(release, running_end[after])
            after = None
        eligible = tuple(line for line in job.eligible if line in kept)
        if not eligible:
            raise ReplanError(f"order {job.name!r} has no line left to run on")
        jobs.append(dataclasses.replace(job, release=release, after=after, eligible=eligible))

    return dataclasses.replace(problem, resources=tuple(resources), jobs=tuple(jobs))
