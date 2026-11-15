import datetime as dt

from scheduler.services.floor_demo import DemoJob, plan_shift

T0 = dt.datetime(2026, 11, 15, 0, 0, tzinfo=dt.UTC)


def job(
    code: str, start_h: int, end_h: int, lines: tuple[str, ...] = ("A",), after: str | None = None
) -> DemoJob:
    return DemoJob(
        id=code,
        planned_start=T0 + dt.timedelta(hours=start_h),
        planned_end=T0 + dt.timedelta(hours=end_h),
        due=T0 + dt.timedelta(hours=24),
        lines=lines,
        after=after,
        status="planned",
    )


def test_nothing_starts_in_the_future() -> None:
    now = T0 + dt.timedelta(hours=5)
    steps = plan_shift([job("a", 0, 4), job("b", 4, 8), job("c", 8, 12)], now)
    assert all(s.start <= now for s in steps)
    assert all(s.end is None or s.end <= now for s in steps)
    assert "c" not in {s.job_id for s in steps}


def test_lines_are_never_double_booked_and_parents_finish_first() -> None:
    now = T0 + dt.timedelta(hours=40)
    jobs = [job("a", 0, 4), job("b", 3, 6), job("r", 0, 2, ("B",), after="a")]
    steps = {s.job_id: s for s in plan_shift(jobs, now)}
    assert steps["b"].start >= steps["a"].end  # type: ignore[operator]
    assert steps["r"].start >= steps["a"].end  # type: ignore[operator]


def test_deterministic_and_a_running_order_blocks_its_line() -> None:
    now = T0 + dt.timedelta(hours=3)
    jobs = [job("a", 0, 6), job("b", 6, 8)]
    first = plan_shift(jobs, now, seed=7)
    assert first == plan_shift(jobs, now, seed=7)
    assert [s.job_id for s in first] == ["a"] and first[0].end is None
