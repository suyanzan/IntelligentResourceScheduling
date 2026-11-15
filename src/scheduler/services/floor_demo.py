"""A made-up duty shift for demos: what an engineer might have recorded up to ``now``.

Pure and deterministic (seeded). Orders start close to plan but sometimes late, run a bit longer
or shorter than planned, and never start before their lines are free or their parent order is done.
Used to fill the floor dashboard and the management report with plausible actuals.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from random import Random

DELAY_NOTES = (
    "Waiting for the line to be cleared",
    "Equipment check before start",
    "Waiting for AUTORP data",
    "Operator handover",
    "Recipe re-validation",
)


@dataclass(frozen=True, slots=True)
class DemoJob:
    id: str
    planned_start: dt.datetime
    planned_end: dt.datetime
    due: dt.datetime
    lines: tuple[str, ...]
    after: str | None
    status: str  # planned, running or done
    actual_start: dt.datetime | None = None
    actual_end: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class DemoStep:
    job_id: str
    start: dt.datetime
    end: dt.datetime | None  # None: still running at ``now``
    note: str | None


def plan_shift(jobs: list[DemoJob], now: dt.datetime, seed: int = 1) -> list[DemoStep]:
    """Steps for every order that would have started by ``now``, in time order."""
    rng = Random(seed)
    free_at: dict[str, dt.datetime] = {}
    ended: dict[str, dt.datetime | None] = {}
    blocked: set[str] = set()  # lines that never become free again within the shift
    steps: list[DemoStep] = []

    for job in sorted(jobs, key=lambda j: (j.planned_start, j.id)):
        if job.status != "planned":
            end = job.actual_end
            ended[job.id] = end
            for line in job.lines:
                if end is None:
                    blocked.add(line)
                elif end > free_at.get(line, end):
                    free_at[line] = end
                else:
                    free_at.setdefault(line, end)
            continue
        if any(line in blocked for line in job.lines):
            continue
        if job.after is not None and ended.get(job.after) is None:
            continue

        jitter = dt.timedelta(minutes=rng.choice((-10, 0, 0, 5, 15, 30, 45, 75)))
        start = job.planned_start + jitter
        for line in job.lines:
            start = max(start, free_at.get(line, start))
        if job.after is not None:
            parent_end = ended[job.after]
            assert parent_end is not None
            start = max(start, parent_end)
        if start > now:
            blocked.update(job.lines)
            continue

        planned = job.planned_end - job.planned_start
        end = start + planned * rng.choice((0.85, 0.95, 1.0, 1.05, 1.2, 1.35))
        note = (
            rng.choice(DELAY_NOTES)
            if start - job.planned_start > dt.timedelta(minutes=40)
            else None
        )
        if end <= now:
            steps.append(DemoStep(job.id, start, end, note))
            ended[job.id] = end
            for line in job.lines:
                free_at[line] = end
        else:
            steps.append(DemoStep(job.id, start, None, note))
            ended[job.id] = None
            blocked.update(job.lines)
    return steps
