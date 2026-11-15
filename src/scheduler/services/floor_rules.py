"""Rules for recording what really happened on the production floor (pure Python).

A job on a released plan is ``planned`` (not started), ``running`` or ``done``. Operators move it
forward with :func:`start_job` and :func:`complete_job`, and undo a slip with :func:`revert_job`.
All datetimes must be timezone-aware. A time may not be in the future (a few minutes of clock
skew are tolerated), and a job cannot finish before it starts.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

PLANNED = "planned"
RUNNING = "running"
DONE = "done"
STATUSES = (PLANNED, RUNNING, DONE)
CLOCK_SKEW = dt.timedelta(minutes=5)


class FloorRuleError(ValueError):
    """The requested update does not fit the job's current state."""


@dataclass(frozen=True, slots=True)
class Actual:
    status: str = PLANNED
    start: dt.datetime | None = None
    end: dt.datetime | None = None


def _check_time(label: str, when: dt.datetime, now: dt.datetime) -> None:
    if when.tzinfo is None:
        raise FloorRuleError(f"{label} must include a time zone")
    if when > now + CLOCK_SKEW:
        raise FloorRuleError(f"{label} is in the future")


def start_job(state: Actual, *, at: dt.datetime, now: dt.datetime) -> Actual:
    """Record the real start time of a job that has not started."""
    if state.status != PLANNED:
        raise FloorRuleError(f"the job is already {state.status}")
    _check_time("the start time", at, now)
    return Actual(RUNNING, at, None)


def complete_job(
    state: Actual,
    *,
    at: dt.datetime,
    now: dt.datetime,
    started_at: dt.datetime | None = None,
) -> Actual:
    """Record the real finish time. A job that was never started needs ``started_at`` too."""
    if state.status == DONE:
        raise FloorRuleError("the job is already done")
    start = started_at or state.start
    if start is None:
        raise FloorRuleError("enter the actual start time as well")
    _check_time("the start time", start, now)
    _check_time("the finish time", at, now)
    if at < start:
        raise FloorRuleError("the job cannot finish before it starts")
    return Actual(DONE, start, at)


def revert_job(state: Actual) -> Actual:
    """Undo the last step: done goes back to running, running goes back to planned."""
    if state.status == DONE:
        return Actual(RUNNING, state.start, None)
    if state.status == RUNNING:
        return Actual(PLANNED, None, None)
    raise FloorRuleError("the job has not started, so there is nothing to undo")
