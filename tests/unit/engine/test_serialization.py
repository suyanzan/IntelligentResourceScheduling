from dataclasses import replace

from scheduler.engine.models import Job, ProblemInstance
from scheduler.engine.serialization import instance_from_dict, instance_hash, instance_to_dict


def test_round_trip(problem: ProblemInstance) -> None:
    assert instance_from_dict(instance_to_dict(problem)) == problem


def test_hash_is_stable_and_hex(problem: ProblemInstance) -> None:
    first = instance_hash(problem)
    assert first == instance_hash(instance_from_dict(instance_to_dict(problem)))
    assert len(first) == 64
    int(first, 16)


def test_hash_changes_with_any_field(problem: ProblemInstance) -> None:
    base = instance_hash(problem)
    changed_job = Job("J1", "Job 1", duration=5, due=4, eligible=("R1", "R2"), priority=2)
    assert instance_hash(replace(problem, jobs=(changed_job, *problem.jobs[1:]))) != base
    assert instance_hash(replace(problem, horizon=problem.horizon + 1)) != base
