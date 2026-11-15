import pytest

from scheduler.engine.models import Job, ProblemInstance, Resource, Window
from scheduler.services.replan_rules import (
    Progress,
    ReplanError,
    expected_end,
    remaining_problem,
)

LINES = (
    Resource("A", "Line A", (Window(0, 72),), capacity=1000),
    Resource("B", "Line B", (Window(0, 72),), capacity=1000),
)


def job(code: str, after: str | None = None, release: int = 0) -> Job:
    return Job(code, code, 0, 48, ("A", "B"), work=4000, after=after, release=release)


PROBLEM = ProblemInstance(
    horizon=72, resources=LINES, jobs=(job("O1"), job("R1", after="O1"), job("O2"), job("O3"))
)


def test_finished_orders_drop_out_and_lines_start_now() -> None:
    progress = {"O1": Progress("done"), "O2": Progress("planned")}
    out = remaining_problem(PROBLEM, progress, now_unit=10)
    assert {j.id for j in out.jobs} == {"R1", "O2", "O3"}
    assert all(j.release == 10 for j in out.jobs)
    assert all(w.start == 10 for r in out.resources for w in r.windows)
    r1 = next(j for j in out.jobs if j.id == "R1")
    assert r1.after is None  # its parent is finished


def test_a_running_order_keeps_its_lines_busy_and_delays_its_follow_up() -> None:
    progress = {"O1": Progress("running", start_unit=8.0, planned_units=6, lines=("A",))}
    out = remaining_problem(PROBLEM, progress, now_unit=10)
    starts = {r.id: r.windows[0].start for r in out.resources}
    assert starts == {"A": 14, "B": 10}
    r1 = next(j for j in out.jobs if j.id == "R1")
    assert r1.after is None and r1.release == 14


def test_follow_up_of_an_open_order_keeps_its_link() -> None:
    out = remaining_problem(PROBLEM, {}, now_unit=0)
    assert next(j for j in out.jobs if j.id == "R1").after == "O1"


def test_an_overrunning_order_is_expected_to_end_after_now() -> None:
    state = Progress("running", start_unit=0.0, planned_units=4, lines=("A",))
    assert expected_end(state, now_unit=10) == 11


def test_nothing_left_or_horizon_over_is_reported() -> None:
    done = {j.id: Progress("done") for j in PROBLEM.jobs}
    with pytest.raises(ReplanError):
        remaining_problem(PROBLEM, done, now_unit=5)
    with pytest.raises(ReplanError):
        remaining_problem(PROBLEM, {}, now_unit=72)


def test_a_line_with_no_time_left_is_dropped() -> None:
    progress = {"O1": Progress("running", start_unit=60.0, planned_units=20, lines=("A",))}
    problem = ProblemInstance(horizon=72, resources=LINES, jobs=(job("O1"), job("O2")))
    with pytest.raises(ReplanError):
        remaining_problem(problem, {**progress, "O2": Progress("running", 60.0, 20, ("B",))}, 65)
    out = remaining_problem(problem, progress, now_unit=65)
    assert [r.id for r in out.resources] == ["B"]
    assert out.jobs[0].eligible == ("B",)
