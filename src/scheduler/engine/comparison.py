"""Side-by-side comparison of two schedule runs.

Pure logic on plain data (standard library only). Differences are always ``b - a``. The
objective is only ranked when it is meaningful to do so: both runs have a schedule, were solved
on identical inputs and optimize the same objective. Otherwise the comparison still reports the
KPI differences but says why no winner is named.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from scheduler.engine.models import Metrics

Better = Literal["a", "b", "tie"]

METRIC_KEYS = ("objective", "on_time_rate", "total_tardiness", "weighted_tardiness", "makespan")


@dataclass(frozen=True, slots=True)
class Placement:
    resource_id: str
    start: int
    end: int
    tardiness: int


@dataclass(frozen=True, slots=True)
class RunView:
    """What the comparison needs to know about one run."""

    run_id: int
    scenario_id: int
    status: str
    weighted: bool
    objective: int | None
    input_hash: str
    metrics: Metrics | None
    placements: dict[str, Placement] = field(default_factory=dict)  # by job code
    job_names: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Delta:
    a: float | None
    b: float | None
    change: float | None  # b - a, None when either side is missing


@dataclass(frozen=True, slots=True)
class JobDiff:
    job_id: str
    job_name: str
    a: Placement | None
    b: Placement | None
    moved: bool  # on both sides, but a different line or start
    tardiness_change: int | None


@dataclass(frozen=True, slots=True)
class Comparison:
    same_scenario: bool
    same_inputs: bool
    objective_comparable: bool
    better: Better | None
    metrics: dict[str, Delta]
    utilization: dict[str, Delta]
    jobs: tuple[JobDiff, ...]
    notes: tuple[str, ...]

    @property
    def moved_jobs(self) -> int:
        return sum(1 for job in self.jobs if job.moved)


def _delta(a: float | None, b: float | None) -> Delta:
    return Delta(a=a, b=b, change=None if a is None or b is None else b - a)


def _rank(objective_a: int, objective_b: int) -> Better:
    """Lower is better (the objective is a tardiness)."""
    if objective_a == objective_b:
        return "tie"
    return "a" if objective_a < objective_b else "b"


def _metric_values(view: RunView) -> dict[str, float | None]:
    m = view.metrics
    return {
        "objective": view.objective,
        "on_time_rate": m.on_time_rate if m else None,
        "total_tardiness": m.total_tardiness if m else None,
        "weighted_tardiness": m.weighted_tardiness if m else None,
        "makespan": m.makespan if m else None,
    }


def _job_diffs(a: RunView, b: RunView) -> tuple[JobDiff, ...]:
    diffs: list[JobDiff] = []
    for job_id in sorted(set(a.placements) | set(b.placements)):
        pa, pb = a.placements.get(job_id), b.placements.get(job_id)
        moved = pa is not None and pb is not None and (
            pa.resource_id != pb.resource_id or pa.start != pb.start
        )
        diffs.append(
            JobDiff(
                job_id=job_id,
                job_name=b.job_names.get(job_id) or a.job_names.get(job_id) or job_id,
                a=pa,
                b=pb,
                moved=moved,
                tardiness_change=None if pa is None or pb is None else pb.tardiness - pa.tardiness,
            )
        )
    return tuple(diffs)


def _notes(a: RunView, b: RunView, *, same_inputs: bool) -> list[str]:
    notes: list[str] = []
    for label, view in (("A", a), ("B", b)):
        if view.metrics is None:
            notes.append(
                f"Run {label} has no schedule ({view.status}); only the other run is shown."
            )
        elif view.status != "OPTIMAL":
            notes.append(
                f"Run {label} is not proven optimal ({view.status}); "
                "a longer time limit may improve it."
            )
    if a.metrics and b.metrics:
        if not same_inputs:
            notes.append(
                "The runs were solved on different inputs, so their objective values are not "
                "directly comparable. Compare the KPIs instead."
            )
        elif a.weighted != b.weighted:
            notes.append("The runs optimize different objectives (weighted and plain tardiness).")
    return notes


def compare(a: RunView, b: RunView) -> Comparison:
    """Compare run ``a`` with run ``b`` (all differences are ``b - a``)."""
    same_inputs = a.input_hash == b.input_hash
    comparable = (
        a.objective is not None
        and b.objective is not None
        and same_inputs
        and a.weighted == b.weighted
    )

    better: Better | None = None
    if comparable:
        assert a.objective is not None and b.objective is not None
        better = _rank(a.objective, b.objective)

    values_a, values_b = _metric_values(a), _metric_values(b)
    metrics = {key: _delta(values_a[key], values_b[key]) for key in METRIC_KEYS}

    util_a = a.metrics.utilization if a.metrics else {}
    util_b = b.metrics.utilization if b.metrics else {}
    utilization = {
        rid: _delta(util_a.get(rid), util_b.get(rid)) for rid in sorted(set(util_a) | set(util_b))
    }

    return Comparison(
        same_scenario=a.scenario_id == b.scenario_id,
        same_inputs=same_inputs,
        objective_comparable=comparable,
        better=better,
        metrics=metrics,
        utilization=utilization,
        jobs=_job_diffs(a, b),
        notes=tuple(_notes(a, b, same_inputs=same_inputs)),
    )
