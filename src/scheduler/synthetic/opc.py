"""Seeded generator of fictional mask-OPC-style compute jobs (all data invented).

Model: a small compute farm with four lines (A: 500, B: 1000, C: 1500, D: 2000 CPUs) that run
around the clock. A job ("MaskOPCOrder 001", ...) needs 1,000..150,000 CPU-hours and may use any
combination of the lines at once, so more lines means a shorter run:
``hours = ceil(cpu_hours / total CPUs of the chosen lines)``. A line runs one job at a time and
cannot interrupt it.

Like :mod:`scheduler.synthetic.generator` it uses only ``Random.random()`` and integer
arithmetic, so a seed gives the same data on every platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from scheduler.engine.models import Job, ProblemInstance, Resource, Window
from scheduler.engine.validation import validate_instance

UNITS_PER_DAY = 24
LINE_CPUS: tuple[int, ...] = (500, 1000, 1500, 2000)
MIN_CPU_HOURS = 1_000
MAX_CPU_HOURS = 150_000
MAINTENANCE_UNITS = 12  # one maintenance block per line when maintenance is enabled


@dataclass(frozen=True, slots=True)
class OpcConfig:
    seed: int = 4
    num_jobs: int = 20
    num_days: int = 30
    maintenance: bool = False

    def __post_init__(self) -> None:
        if self.num_jobs < 1:
            raise ValueError("num_jobs must be at least 1")
        if self.num_days < 7:
            raise ValueError("num_days must be at least 7")


OPC_PRESETS: dict[str, OpcConfig] = {"opc": OpcConfig()}


def _randint(rng: Random, low: int, high: int) -> int:
    return low + int(rng.random() * (high - low + 1))


def generate_opc(config: OpcConfig) -> ProblemInstance:
    """Generate a deterministic OPC-style instance from ``config``."""
    rng = Random(config.seed)
    horizon = config.num_days * UNITS_PER_DAY

    resources = tuple(_make_line(rng, i, cpus, horizon, config) for i, cpus in enumerate(LINE_CPUS))
    ids = tuple(r.id for r in resources)
    total_cpus = sum(LINE_CPUS)
    jobs = tuple(_make_job(rng, n, ids, total_cpus, horizon) for n in range(config.num_jobs))

    problem = ProblemInstance(horizon=horizon, resources=resources, jobs=jobs)
    issues = validate_instance(problem)
    if issues:  # pragma: no cover - guards against generator bugs
        raise ValueError("generator produced an invalid instance: " + "; ".join(issues))
    return problem


def _make_line(rng: Random, index: int, cpus: int, horizon: int, config: OpcConfig) -> Resource:
    windows = (Window(0, horizon),)
    if config.maintenance:
        start = _randint(rng, 24, horizon - 24 - MAINTENANCE_UNITS)
        windows = (Window(0, start), Window(start + MAINTENANCE_UNITS, horizon))
    letter = chr(ord("A") + index)
    return Resource(id=letter, name=f"Line {letter}", windows=windows, capacity=cpus)


def _make_job(
    rng: Random, index: int, line_ids: tuple[str, ...], total_cpus: int, horizon: int
) -> Job:
    # Squaring the draw makes small jobs more common than huge ones.
    draw = rng.random()
    work = MIN_CPU_HOURS + int(draw * draw * (MAX_CPU_HOURS - MIN_CPU_HOURS))
    priority = _randint(rng, 1, 5)
    fastest = -(-work // total_cpus)  # hours if it used every line
    due = fastest + _randint(rng, 0, horizon // 3)
    return Job(
        id=f"O{index + 1:03d}",
        name=f"MaskOPCOrder {index + 1:03d}",
        duration=0,
        due=due,
        eligible=line_ids,
        priority=priority,
        work=work,
    )
