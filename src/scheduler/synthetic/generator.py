"""Seeded generator of fully fictional scheduling instances.

Reproducibility: only ``random.Random.random()`` and integer arithmetic are used, so a given
seed produces the identical instance on every platform and Python version (``randint``,
``choice`` and ``shuffle`` are deliberately avoided because their algorithms have changed
between Python releases).

Model of the fictional shop floor (1 time unit = 1 hour, 24 units per day, day 0 is a Monday):

* Each resource ("Line A", "Line B", ...) follows one shift pattern on working days.
* Saturdays and Sundays are closed, and each resource has one random maintenance day closed.
* Jobs ("Order 001", ...) have a duration of 1..8 units, 1..3 eligible lines, a priority 1..5,
  an optional release time and a due date.

The generator guarantees a structurally valid instance (it passes
:func:`scheduler.engine.validation.validate_instance`) but not that the instance is feasible
within the horizon; the presets are sized so that they are.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from scheduler.engine.models import Job, ProblemInstance, Resource, Window
from scheduler.engine.validation import validate_instance
from scheduler.synthetic.opc import OPC_PRESETS, generate_opc

UNITS_PER_DAY = 24
MAX_DURATION = 8  # the shortest shift is 8 units, so every job fits in a shift
MAX_ELIGIBLE = 3

# (shift start hour, shift end hour) per working day
SHIFT_PATTERNS: tuple[tuple[int, int], ...] = ((8, 16), (6, 18), (6, 22))


@dataclass(frozen=True, slots=True)
class GeneratorConfig:
    seed: int = 42
    num_resources: int = 3
    num_jobs: int = 20
    num_days: int = 14
    release_fraction: float = 0.2

    def __post_init__(self) -> None:
        if self.num_resources < 1:
            raise ValueError("num_resources must be at least 1")
        if self.num_jobs < 1:
            raise ValueError("num_jobs must be at least 1")
        if self.num_days < 3:
            raise ValueError("num_days must be at least 3")
        if not 0.0 <= self.release_fraction <= 1.0:
            raise ValueError("release_fraction must be between 0 and 1")


PRESETS: dict[str, GeneratorConfig] = {
    "tiny": GeneratorConfig(seed=1, num_resources=2, num_jobs=6, num_days=7),
    "small": GeneratorConfig(seed=2, num_resources=3, num_jobs=20, num_days=14),
    "medium": GeneratorConfig(seed=3, num_resources=5, num_jobs=40, num_days=14),
}


def preset(name: str) -> ProblemInstance:
    """Generate one of the named presets (``tiny``, ``small``, ``medium``, ``opc``)."""
    if name in OPC_PRESETS:
        return generate_opc(OPC_PRESETS[name])
    try:
        config = PRESETS[name]
    except KeyError:
        choices = sorted([*PRESETS, *OPC_PRESETS])
        raise ValueError(f"unknown preset {name!r}; choose from {choices}") from None
    return generate(config)


def generate(config: GeneratorConfig) -> ProblemInstance:
    """Generate a deterministic synthetic instance from ``config``."""
    rng = Random(config.seed)
    horizon = config.num_days * UNITS_PER_DAY

    resources = tuple(_make_resource(rng, k, config.num_days) for k in range(config.num_resources))
    resource_ids = [r.id for r in resources]
    jobs = tuple(_make_job(rng, n, resource_ids, horizon, config) for n in range(config.num_jobs))

    problem = ProblemInstance(horizon=horizon, resources=resources, jobs=jobs)
    issues = validate_instance(problem)
    if issues:  # pragma: no cover - guards against generator bugs
        raise ValueError("generator produced an invalid instance: " + "; ".join(issues))
    return problem


def _randint(rng: Random, low: int, high: int) -> int:
    """Uniform integer in ``[low, high]`` built only on ``random()``."""
    return low + int(rng.random() * (high - low + 1))


def _make_resource(rng: Random, index: int, num_days: int) -> Resource:
    shift_start, shift_end = SHIFT_PATTERNS[_randint(rng, 0, len(SHIFT_PATTERNS) - 1)]
    working_days = [d for d in range(num_days) if d % 7 < 5]
    maintenance_day = working_days[_randint(rng, 0, len(working_days) - 1)]

    windows = tuple(
        Window(day * UNITS_PER_DAY + shift_start, day * UNITS_PER_DAY + shift_end)
        for day in working_days
        if day != maintenance_day
    )
    return Resource(id=f"R{index + 1}", name=f"Line {chr(ord('A') + index % 26)}", windows=windows)


def _make_job(
    rng: Random, index: int, resource_ids: list[str], horizon: int, config: GeneratorConfig
) -> Job:
    duration = _randint(rng, 1, MAX_DURATION)
    priority = _randint(rng, 1, 5)

    pool = list(resource_ids)
    count = _randint(rng, 1, min(MAX_ELIGIBLE, len(pool)))
    eligible: list[str] = []
    for _ in range(count):
        eligible.append(pool.pop(_randint(rng, 0, len(pool) - 1)))
    eligible.sort()

    release = _randint(rng, 0, horizon // 4) if rng.random() < config.release_fraction else 0
    due = release + duration + _randint(rng, 0, horizon // 3)

    return Job(
        id=f"J{index + 1:03d}",
        name=f"Order {index + 1:03d}",
        duration=duration,
        due=due,
        eligible=tuple(eligible),
        priority=priority,
        release=release,
    )
