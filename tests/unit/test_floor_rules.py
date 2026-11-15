"""State rules for floor updates (pure Python)."""

import datetime as dt

import pytest

from scheduler.services.floor_rules import (
    Actual,
    FloorRuleError,
    complete_job,
    revert_job,
    start_job,
)

TZ = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime(2026, 11, 15, 19, 0, tzinfo=TZ)


def at(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 11, 15, hour, minute, tzinfo=TZ)


def test_start_then_complete() -> None:
    running = start_job(Actual(), at=at(17), now=NOW)
    assert (running.status, running.start, running.end) == ("running", at(17), None)
    done = complete_job(running, at=at(18, 30), now=NOW)
    assert (done.status, done.start, done.end) == ("done", at(17), at(18, 30))


def test_complete_without_start_needs_the_start_time() -> None:
    with pytest.raises(FloorRuleError, match="actual start time"):
        complete_job(Actual(), at=at(18), now=NOW)
    done = complete_job(Actual(), at=at(18), now=NOW, started_at=at(16))
    assert (done.start, done.end) == (at(16), at(18))


def test_cannot_finish_before_start_or_in_the_future() -> None:
    running = start_job(Actual(), at=at(17), now=NOW)
    with pytest.raises(FloorRuleError, match="before it starts"):
        complete_job(running, at=at(16), now=NOW)
    with pytest.raises(FloorRuleError, match="future"):
        complete_job(running, at=at(21), now=NOW)
    with pytest.raises(FloorRuleError, match="future"):
        start_job(Actual(), at=at(20), now=NOW)


def test_a_few_minutes_of_clock_skew_is_tolerated() -> None:
    assert start_job(Actual(), at=NOW + dt.timedelta(minutes=4), now=NOW).status == "running"


def test_naive_datetimes_are_refused() -> None:
    with pytest.raises(FloorRuleError, match="time zone"):
        start_job(Actual(), at=dt.datetime(2026, 11, 15, 10, 0), now=NOW)


def test_wrong_state_transitions() -> None:
    running = start_job(Actual(), at=at(17), now=NOW)
    with pytest.raises(FloorRuleError, match="already running"):
        start_job(running, at=at(18), now=NOW)
    done = complete_job(running, at=at(18), now=NOW)
    with pytest.raises(FloorRuleError, match="already done"):
        complete_job(done, at=at(18, 30), now=NOW)
    with pytest.raises(FloorRuleError, match="already done"):
        start_job(done, at=at(18, 30), now=NOW)


def test_revert_walks_back_one_step() -> None:
    done = complete_job(start_job(Actual(), at=at(17), now=NOW), at=at(18), now=NOW)
    back = revert_job(done)
    assert (back.status, back.start, back.end) == ("running", at(17), None)
    planned = revert_job(back)
    assert (planned.status, planned.start, planned.end) == ("planned", None, None)
    with pytest.raises(FloorRuleError, match="nothing to undo"):
        revert_job(planned)
