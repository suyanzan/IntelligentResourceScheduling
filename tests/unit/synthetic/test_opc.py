import pytest

from scheduler.engine.serialization import instance_hash
from scheduler.engine.validation import validate_instance
from scheduler.synthetic.generator import preset
from scheduler.synthetic.opc import (
    LINE_CPUS,
    MAX_CPU_HOURS,
    MIN_CPU_HOURS,
    OPC_PRESETS,
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


LIVE_HASH = "07f2ab01896d08c6bde436089fa51d1e51367fce8d5eea73d8d59586bcfa18fe"


def test_live_preset_golden_hash() -> None:
    assert instance_hash(generate_opc(OPC_PRESETS["opc_live"])) == LIVE_HASH


def test_live_preset_has_autorp_diffusion_cap_and_busy_lines() -> None:
    problem = generate_opc(OPC_PRESETS["opc_live"])
    jobs = {j.id: j for j in problem.jobs}
    opc = [j for j in problem.jobs if j.id.startswith("O")]
    assert len(opc) == 20 and len(problem.jobs) == 40
    assert problem.max_merge_capacity == 3000
    for order in opc:
        follow = jobs["R" + order.id[1:]]
        assert follow.after == order.id and follow.name.startswith("AUTORP ")
        assert follow.work == max(1, order.work * 42 // 100)  # type: ignore[operator]
        assert follow.due == order.due and follow.release == 0
    diffusion = [j for j in opc if j.layer == "DIFFUSION"]
    assert diffusion and all(j.cycle_limit == 12 and j.release >= 1 for j in diffusion)
    assert all(j.cycle_limit is None and j.release == 0 for j in opc if not j.layer)
    starts = {r.id: r.windows[0].start for r in problem.resources}
    assert starts == {"A": 36, "B": 36, "C": 36, "D": 0}


def test_live_preset_start_schedule_is_valid_and_never_idles() -> None:
    from scheduler.engine.heuristic import best_start_schedule
    from scheduler.engine.metrics import verify_schedule

    problem = generate_opc(OPC_PRESETS["opc_live"])
    schedule = best_start_schedule(problem, no_idle=True)
    assert schedule is not None
    assert verify_schedule(problem, schedule, no_idle=True) == []
