from dataclasses import replace

from scheduler.engine.models import Job, ProblemInstance, Resource, Window
from scheduler.engine.validation import validate_instance


def _has(issues: list[str], *needles: str) -> bool:
    return any(all(n in issue for n in needles) for issue in issues)


def _with_job(problem: ProblemInstance, job: Job) -> ProblemInstance:
    return replace(problem, jobs=(*problem.jobs, job))


def test_valid_instance_has_no_issues(problem: ProblemInstance) -> None:
    assert validate_instance(problem) == []


def test_non_positive_horizon(problem: ProblemInstance) -> None:
    assert _has(validate_instance(replace(problem, horizon=0)), "horizon")


def test_duplicate_ids(problem: ProblemInstance) -> None:
    dup_job = Job("J1", "Again", duration=1, due=5, eligible=("R2",))
    dup_res = Resource("R2", "Again", (Window(0, 5),))
    issues = validate_instance(
        replace(problem, jobs=(*problem.jobs, dup_job), resources=(*problem.resources, dup_res))
    )
    assert _has(issues, "duplicate job id", "J1")
    assert _has(issues, "duplicate resource id", "R2")


def test_job_with_no_eligible_resources(problem: ProblemInstance) -> None:
    issues = validate_instance(_with_job(problem, Job("J9", "x", 1, 5, eligible=())))
    assert _has(issues, "J9", "no eligible resources")


def test_job_with_unknown_resource(problem: ProblemInstance) -> None:
    issues = validate_instance(_with_job(problem, Job("J9", "x", 1, 5, eligible=("R99",))))
    assert _has(issues, "J9", "unknown resource", "R99")


def test_bad_duration_priority_release_due(problem: ProblemInstance) -> None:
    bad = Job("J9", "x", duration=0, due=-1, eligible=("R2",), priority=6, release=-2)
    issues = validate_instance(_with_job(problem, bad))
    assert _has(issues, "J9", "duration must be positive")
    assert _has(issues, "J9", "priority must be between 1 and 5")
    assert _has(issues, "J9", "release must be non-negative")
    assert _has(issues, "J9", "due date must be non-negative")


def test_empty_and_reversed_window(problem: ProblemInstance) -> None:
    res = Resource("R3", "x", (Window(5, 5), Window(9, 7)))
    issues = validate_instance(replace(problem, resources=(*problem.resources, res)))
    assert _has(issues, "R3", "[5, 5)", "empty or reversed")
    assert _has(issues, "R3", "[9, 7)", "empty or reversed")


def test_window_outside_horizon(problem: ProblemInstance) -> None:
    res = Resource("R3", "x", (Window(20, 30), Window(-1, 3)))
    issues = validate_instance(replace(problem, resources=(*problem.resources, res)))
    assert _has(issues, "R3", "[20, 30)", "outside the horizon")
    assert _has(issues, "R3", "[-1, 3)", "outside the horizon")


def test_overlapping_windows_but_touching_is_fine(problem: ProblemInstance) -> None:
    touching = Resource("R3", "x", (Window(0, 8), Window(8, 16)))
    assert validate_instance(replace(problem, resources=(*problem.resources, touching))) == []

    overlapping = Resource("R4", "x", (Window(0, 9), Window(8, 16)))
    issues = validate_instance(replace(problem, resources=(*problem.resources, overlapping)))
    assert _has(issues, "R4", "overlapping windows")


def test_job_too_long_for_any_window(problem: ProblemInstance) -> None:
    # R1's longest window is 8 units, so a 9-unit job restricted to R1 cannot fit.
    issues = validate_instance(_with_job(problem, Job("J9", "x", 9, 30, eligible=("R1",))))
    assert _has(issues, "J9", "cannot fit")


def test_release_pushes_job_out_of_window(problem: ProblemInstance) -> None:
    # Window [10, 18) with release 15 leaves only 3 units, so a 4-unit job cannot fit on R1.
    late = Job("J9", "x", 4, 30, eligible=("R1",), release=15)
    assert _has(validate_instance(_with_job(problem, late)), "J9", "cannot fit")


def test_release_beyond_horizon(problem: ProblemInstance) -> None:
    late = Job("J9", "x", 4, 30, eligible=("R2",), release=22)
    assert _has(validate_instance(_with_job(problem, late)), "J9", "cannot fit")


def test_fits_on_second_eligible_resource(problem: ProblemInstance) -> None:
    # Too long for R1 (max window 8) but fine on R2 (24 units).
    job = Job("J9", "x", 9, 30, eligible=("R1", "R2"))
    assert validate_instance(_with_job(problem, job)) == []
