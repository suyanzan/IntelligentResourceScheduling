import pytest

from scheduler.engine.serialization import instance_hash
from scheduler.engine.validation import validate_instance
from scheduler.synthetic.generator import preset
from scheduler.synthetic.opc import (
    LINE_CPUS,
    MAX_CPU_HOURS,
    MIN_CPU_HOURS,
    OpcConfig,
    generate_opc,
)

GOLDEN = {
    False: "086ba8ae3454b4bd25b3efc5be2fa1584c5d46df101b0f0ae94fc1ec2f06fed1",
    True: "7aebee5662b7d61688b11b344a3b72450bbd24f98bc79484bcba1201fecc2f0f",
}


@pytest.mark.parametrize("maintenance", [False, True])
def test_golden_hash(maintenance: bool) -> None:
    assert instance_hash(generate_opc(OpcConfig(maintenance=maintenance))) == GOLDEN[maintenance]


def test_preset_is_the_default_opc_config() -> None:
    assert preset("opc") == generate_opc(OpcConfig())


def test_lines_and_jobs_match_the_brief() -> None:
    problem = generate_opc(OpcConfig())
    assert validate_instance(problem) == []
    assert [r.capacity for r in problem.resources] == list(LINE_CPUS)
    assert [r.name for r in problem.resources] == ["Line A", "Line B", "Line C", "Line D"]
    assert len(problem.jobs) == 20
    assert problem.jobs[0].name == "MaskOPCOrder 001"
    assert problem.jobs[-1].name == "MaskOPCOrder 020"
    for job in problem.jobs:
        assert job.work is not None and MIN_CPU_HOURS <= job.work <= MAX_CPU_HOURS
        assert set(job.eligible) == {"A", "B", "C", "D"}
        assert 1 <= job.priority <= 5


def test_lines_run_around_the_clock_unless_maintenance_is_on() -> None:
    plain = generate_opc(OpcConfig(num_days=10))
    assert all(len(r.windows) == 1 and r.windows[0].length == 240 for r in plain.resources)
    with_maintenance = generate_opc(OpcConfig(num_days=10, maintenance=True))
    for r in with_maintenance.resources:
        assert len(r.windows) == 2
        assert r.windows[1].start - r.windows[0].end == 12


def test_same_seed_same_data() -> None:
    assert generate_opc(OpcConfig(seed=9)) == generate_opc(OpcConfig(seed=9))
    assert generate_opc(OpcConfig(seed=9)) != generate_opc(OpcConfig(seed=10))


@pytest.mark.parametrize("kwargs", [{"num_jobs": 0}, {"num_days": 6}])
def test_bad_config_is_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        OpcConfig(**kwargs)
