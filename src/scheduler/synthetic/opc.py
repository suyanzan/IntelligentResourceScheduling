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

# "Live" scenario: five lines, orders arrive over time, some in the DIFFUSION layer, each OPC
# order is followed by an AUTORP order, merging is capped, and every due date is today, tomorrow
# or the day after (the end of that day).
LIVE_LINE_CPUS: tuple[int, ...] = (500, 1000, 1500, 2000, 1500)  # lines A..E
DUE_DAYS = 3
MERGE_CAP_CPUS = 3000  # a job may merge lines up to this many CPUs in total
AUTORP_PERCENT = 42  # AUTORP work as a percentage of its OPC order's work
CYCLE_LIMIT_UNITS = 12  # a DIFFUSION order should finish within 12 h of arriving
DIFFUSION_PERCENT = 25  # share of OPC orders that are DIFFUSION
DIFFUSION_MAX_CPU_HOURS = 20_000  # DIFFUSION orders are small: one free line can make 12 h
ARRIVAL_DAYS = 2  # DIFFUSION orders arrive during the first two days
LIVE_HORIZON_UNITS = DUE_DAYS * UNITS_PER_DAY  # the live sample covers exactly three days
LIVE_MAX_CPU_HOURS = 15_000  # three days of work must fit even when the plan starts late
BUSY_LINES = ("A", "B", "C")  # lines still running the current order when the plan starts


@dataclass(frozen=True, slots=True)
class OpcConfig:
    seed: int = 4
    num_jobs: int = 20
    num_days: int = 30
    maintenance: bool = False
    live: bool = False  # AUTORP follow-ups, DIFFUSION arrivals, merge cap, lines busy at start
    busy_until: int = 36  # live only: units until lines A, B and C finish the current order
    now_unit: int = 0  # live only: the plan starts this many units after midnight of day 0

    def __post_init__(self) -> None:
        if self.num_jobs < 1:
            raise ValueError("num_jobs must be at least 1")
        if self.num_days < 7:
            raise ValueError("num_days must be at least 7")


OPC_PRESETS: dict[str, OpcConfig] = {"opc": OpcConfig(), "opc_live": OpcConfig(live=True)}


def _randint(rng: Random, low: int, high: int) -> int:
    return low + int(rng.random() * (high - low + 1))


def generate_opc(config: OpcConfig) -> ProblemInstance:
    """Generate a deterministic OPC-style instance from ``config``."""
    if config.live:
        return _generate_live(config)
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
    windows: tuple[Window, ...] = (Window(0, horizon),)
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


def _generate_live(config: OpcConfig) -> ProblemInstance:
    """Orders that arrive over time, with AUTORP follow-ups and DIFFUSION cycle limits."""
    rng = Random(config.seed)
    horizon = LIVE_HORIZON_UNITS
    resources = tuple(
        Resource(
            id=chr(ord("A") + i),
            name=f"Line {chr(ord('A') + i)}",
            windows=(
                Window(
                    config.busy_until if chr(ord("A") + i) in BUSY_LINES else config.now_unit,
                    horizon,
                ),
            ),
            capacity=cpus,
        )
        for i, cpus in enumerate(LIVE_LINE_CPUS)
    )
    ids = tuple(r.id for r in resources)

    jobs: list[Job] = []
    for index in range(config.num_jobs):
        number = f"{index + 1:03d}"
        diffusion = rng.random() * 100 < DIFFUSION_PERCENT
        draw = rng.random()
        priority = _randint(rng, 1, 5)
        if diffusion:
            work = MIN_CPU_HOURS + int(draw * (DIFFUSION_MAX_CPU_HOURS - MIN_CPU_HOURS))
            span = min(
                ARRIVAL_DAYS * UNITS_PER_DAY,
                DUE_DAYS * UNITS_PER_DAY - CYCLE_LIMIT_UNITS - config.now_unit,
            )
            release = config.now_unit + _randint(rng, 1, max(1, span))
            due = _due_at_end_of_day(rng)
            if due < release + CYCLE_LIMIT_UNITS:  # leave room for the 12 h cycle
                due = max(DUE_DAYS * UNITS_PER_DAY, release + CYCLE_LIMIT_UNITS)
        else:
            work = MIN_CPU_HOURS + int(draw * draw * (LIVE_MAX_CPU_HOURS - MIN_CPU_HOURS))
            release = config.now_unit
            due = _due_at_end_of_day(rng)
        jobs.append(
            Job(
                id=f"O{number}",
                name=f"MaskOPCOrder {number}",
                duration=0,
                due=due,
                eligible=ids,
                priority=priority,
                release=release,
                work=work,
                cycle_limit=CYCLE_LIMIT_UNITS if diffusion else None,
                layer="DIFFUSION" if diffusion else "",
            )
        )
        jobs.append(
            Job(
                id=f"R{number}",
                name=f"AUTORP {number}",
                duration=0,
                due=due,
                eligible=ids,
                priority=priority,
                work=max(1, work * AUTORP_PERCENT // 100),
                after=f"O{number}",
            )
        )

    problem = ProblemInstance(
        horizon=horizon, resources=resources, jobs=tuple(jobs), max_merge_capacity=MERGE_CAP_CPUS
    )
    issues = validate_instance(problem)
    if issues:  # pragma: no cover - guards against generator bugs
        raise ValueError("generator produced an invalid instance: " + "; ".join(issues))
    return problem


def _due_at_end_of_day(rng: Random) -> int:
    """End of today, tomorrow or the day after (hour 24, 48 or 72)."""
    return (_randint(rng, 1, DUE_DAYS)) * UNITS_PER_DAY
