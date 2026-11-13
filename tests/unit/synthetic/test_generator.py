import pytest

from scheduler.engine.serialization import instance_hash
from scheduler.engine.validation import validate_instance
from scheduler.synthetic.generator import (
    MAX_DURATION,
    PRESETS,
    UNITS_PER_DAY,
    GeneratorConfig,
    generate,
    preset,
)

# Golden hashes pin the exact generated data. If the generator changes on purpose, update them
# together with the change; an accidental change means seeded fixtures stopped being reproducible.
GOLDEN_HASHES = {
    "tiny": "f45ab17506a793ce00393d420a11d4f4b09671b57590a6cd8ee23f72c3b7ab55",
    "small": "f4c8ea841188a8d9492b7152d5b203e78644a86cb1f0a28ec8c4fec1cf89c7a7",
    "medium": "bc7ee5c8eb3c73f6e9046127515dc5ce9ad8b7ff7a1b36cdccb8b6984d0571b7",
}


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_preset_matches_golden_hash(name: str) -> None:
    assert instance_hash(preset(name)) == GOLDEN_HASHES[name]


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_preset_is_valid_and_sized(name: str) -> None:
    config = PRESETS[name]
    problem = preset(name)
    assert validate_instance(problem) == []
    assert len(problem.jobs) == config.num_jobs
    assert len(problem.resources) == config.num_resources
    assert problem.horizon == config.num_days * UNITS_PER_DAY


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_preset_has_spare_capacity(name: str) -> None:
    problem = preset(name)
    load = sum(j.duration for j in problem.jobs)
    capacity = sum(w.length for r in problem.resources for w in r.windows)
    assert load < 0.7 * capacity


def test_same_seed_same_data_different_seed_different_data() -> None:
    a = generate(GeneratorConfig(seed=7))
    assert a == generate(GeneratorConfig(seed=7))
    assert instance_hash(a) != instance_hash(generate(GeneratorConfig(seed=8)))


def test_job_properties_are_in_range() -> None:
    problem = generate(GeneratorConfig(seed=11, num_resources=4, num_jobs=60))
    ids = {r.id for r in problem.resources}
    for job in problem.jobs:
        assert 1 <= job.duration <= MAX_DURATION
        assert 1 <= job.priority <= 5
        assert 1 <= len(job.eligible) <= 3
        assert set(job.eligible) <= ids
        assert len(set(job.eligible)) == len(job.eligible)
        assert job.due >= job.release + job.duration


def test_calendar_has_no_weekend_work_and_one_maintenance_day() -> None:
    config = GeneratorConfig(seed=5, num_resources=3, num_days=14)
    for resource in generate(config).resources:
        days = {w.start // UNITS_PER_DAY for w in resource.windows}
        assert all(d % 7 < 5 for d in days)
        assert len(days) == 10 - 1  # 10 weekdays in 14 days, minus one maintenance day
        for w in resource.windows:
            assert w.start // UNITS_PER_DAY == (w.end - 1) // UNITS_PER_DAY


@pytest.mark.parametrize(
    "kwargs",
    [
        {"num_resources": 0},
        {"num_jobs": 0},
        {"num_days": 2},
        {"release_fraction": 1.5},
    ],
)
def test_invalid_config_is_rejected(kwargs: dict[str, int | float]) -> None:
    with pytest.raises(ValueError):
        GeneratorConfig(**kwargs)  # type: ignore[arg-type]


def test_unknown_preset() -> None:
    with pytest.raises(ValueError, match="unknown preset"):
        preset("huge")
