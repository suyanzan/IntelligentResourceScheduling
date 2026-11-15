"""The no-idle rule and the start-schedule heuristic (pure Python, no solver)."""

from scheduler.engine.heuristic import sequential_merge_schedule
from scheduler.engine.metrics import idle_violations, objective_value, verify_schedule
from scheduler.engine.models import Assignment, Job, ProblemInstance, Resource, Window
from scheduler.synthetic.generator import preset

A = Resource("A", "Line A", (Window(0, 100),), capacity=500)
B = Resource("B", "Line B", (Window(0, 100),), capacity=1000)


def opc(job_id: str, work: int, due: int = 50) -> Job:
    return Job(job_id, job_id, duration=0, due=due, eligible=("A", "B"), work=work)


def problem(*jobs: Job, resources: tuple[Resource, ...] = (A, B)) -> ProblemInstance:
    return ProblemInstance(horizon=100, resources=resources, jobs=jobs)


def test_a_line_idle_before_the_last_start_is_reported() -> None:
    p = problem(opc("J1", 5_000), opc("J2", 1_500))
    # J1 runs on B for 5 units while A sits idle; J2 (1 unit on A+B) only starts at 5.
    rows = [Assignment("J1", "B", 0, 5), Assignment("J2", "A", 5, 6), Assignment("J2", "B", 5, 6)]
    assert verify_schedule(p, rows) == []
    problems = idle_violations(p, rows)
    assert any("'A' is idle during [0, 5)" in v for v in problems)
    assert verify_schedule(p, rows, no_idle=True) == problems


def test_a_compact_schedule_passes() -> None:
    p = problem(opc("J1", 5_000), opc("J2", 1_500))
    rows = [
        Assignment("J1", "A", 0, 4), Assignment("J1", "B", 0, 4),  # 5000 / 1500 -> 4 units
        Assignment("J2", "A", 4, 5), Assignment("J2", "B", 4, 5),
    ]
    assert verify_schedule(p, rows, no_idle=True) == []


def test_idling_after_every_job_has_started_is_allowed() -> None:
    p = problem(opc("J1", 5_000), opc("J2", 1_000))
    # Both start at 0; J2 finishes early on A (2 units) and A then idles, but nothing waits.
    rows = [Assignment("J1", "B", 0, 5), Assignment("J2", "A", 0, 2)]
    assert verify_schedule(p, rows, no_idle=True) == []


def test_closed_periods_count_as_busy() -> None:
    gap_line = Resource("A", "Line A", (Window(0, 4), Window(6, 100)), capacity=500)
    p = problem(opc("J1", 1_000), opc("J2", 500), resources=(gap_line,))
    rows = [Assignment("J1", "A", 0, 2), Assignment("J2", "A", 2, 3)]
    # 3..6 is neither busy nor closed (the window ends at 4 but J2 ended at 3): not a violation
    # because J2 is the last job and starts at 2, so nothing waits after 2.
    assert verify_schedule(p, rows, no_idle=True) == []
    late = [Assignment("J1", "A", 0, 2), Assignment("J2", "A", 6, 7)]
    assert any("idle during [2, 4)" in v for v in idle_violations(p, late))
    assert not any("[4, 6)" in v for v in idle_violations(p, late))  # closed, so not idle


def test_jobs_that_cannot_use_a_line_do_not_make_it_wait() -> None:
    only_a = Job("J2", "J2", duration=0, due=50, eligible=("A",), work=500)
    p = problem(opc("J1", 5_000), only_a)
    # B finishes J1 and then has nothing it may run: no violation even though J2 starts at 6.
    rows = [Assignment("J1", "B", 0, 5), Assignment("J2", "A", 6, 7)]
    problems = idle_violations(p, rows)
    assert not any("'B'" in v for v in problems)
    assert any("'A' is idle during [0, 6)" in v for v in problems)


def test_heuristic_schedule_is_valid_and_never_idles() -> None:
    p = preset("opc")
    schedule = sequential_merge_schedule(p)
    assert schedule is not None
    assert verify_schedule(p, schedule, no_idle=True) == []
    assert len(schedule) == len(p.jobs) * len(p.resources)
    # It beats a naive run-everything-on-the-smallest-line approach by a wide margin.
    assert objective_value(p, schedule) < 1_000


def test_heuristic_does_not_apply_to_ordinary_jobs_or_calendars() -> None:
    assert sequential_merge_schedule(preset("small")) is None
    maintenance = Resource("A", "A", (Window(0, 40), Window(50, 100)), capacity=500)
    assert sequential_merge_schedule(problem(opc("J1", 500), resources=(maintenance,))) is None
