"""The no-idle rule and the start-schedule heuristic (pure Python, no solver)."""

from scheduler.engine.heuristic import dispatch_schedule, sequential_merge_schedule
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


def test_a_line_may_idle_before_a_release_but_not_while_a_job_waits() -> None:
    late = Job("J", "J", duration=0, due=50, eligible=("A", "B"), work=500, release=5)
    p = problem(late)
    assert verify_schedule(p, [Assignment("J", "A", 5, 6)], no_idle=True) == []
    waiting = [Assignment("J", "A", 8, 9)]  # available at 5, starts at 8, A idle during [5, 8)
    found = idle_violations(p, waiting)
    assert any("'A' is idle during [5, 8)" in v for v in found)
    assert any("'B' is idle during [5, 8)" in v for v in found)


def test_a_job_that_comes_after_another_waits_from_its_end() -> None:
    first = opc("J1", 500)
    second = Job("J2", "J2", duration=0, due=50, eligible=("A",), work=500, after="J1")
    p = problem(first, second)
    ok = [Assignment("J1", "A", 0, 1), Assignment("J2", "A", 1, 2)]
    assert verify_schedule(p, ok, no_idle=True) == []
    gap = [Assignment("J1", "A", 0, 1), Assignment("J2", "A", 3, 4)]
    assert any("'A' is idle during [1, 3)" in v for v in idle_violations(p, gap))


def test_dispatch_schedule_is_valid_work_conserving_and_respects_links_and_cap() -> None:
    lines = tuple(
        Resource(code, code, (Window(0, 300),), capacity=cap)
        for code, cap in (("A", 500), ("B", 1000), ("C", 1500), ("D", 2000))
    )
    eligible = ("A", "B", "C", "D")
    jobs = (
        Job("O1", "O1", duration=0, due=40, eligible=eligible, work=30_000, priority=3),
        Job("R1", "R1", duration=0, due=40, eligible=eligible, work=12_600, after="O1"),
        Job("O2", "O2", duration=0, due=60, eligible=eligible, work=20_000, priority=2),
    )
    p = ProblemInstance(horizon=300, resources=lines, jobs=jobs, max_merge_capacity=3000)
    schedule = dispatch_schedule(p)
    assert schedule is not None
    assert verify_schedule(p, schedule, no_idle=True) == []
    ends = {a.job_id: a.end for a in schedule}
    starts = {a.job_id: a.start for a in schedule}
    assert starts["R1"] >= ends["O1"]
    for job_id in ("O1", "O2", "R1"):
        used = [a.resource_id for a in schedule if a.job_id == job_id]
        assert sum(p.resource_by_id()[r].capacity for r in used) <= 3000


def test_dispatch_schedule_gives_a_diffusion_job_a_free_line() -> None:
    busy = tuple(
        Resource(c, c, (Window(40, 300),), capacity=cap)
        for c, cap in (("A", 500), ("B", 1000), ("C", 1500))
    )
    lines = (*busy, Resource("D", "D", (Window(0, 300),), capacity=2000))
    eligible = ("A", "B", "C", "D")
    diffusion = Job(
        "DIFF", "DIFF", duration=0, due=200, eligible=eligible, work=20_000, release=10,
        cycle_limit=12, layer="DIFFUSION",
    )
    p = ProblemInstance(horizon=300, resources=lines, jobs=(diffusion,), max_merge_capacity=3000)
    schedule = dispatch_schedule(p)
    assert schedule is not None
    assert {a.resource_id for a in schedule} == {"D"}
    assert (schedule[0].start, schedule[0].end) == (10, 20)
