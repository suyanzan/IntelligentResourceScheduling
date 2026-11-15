"""Compare two stored runs. Loads them through the scheduling service and hands plain data to
the pure comparison logic in :mod:`scheduler.engine.comparison`."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from scheduler.db import models as orm
from scheduler.engine import comparison
from scheduler.engine.models import Metrics
from scheduler.services import scheduling_service


@dataclass(frozen=True, slots=True)
class RunComparison:
    a: orm.ScheduleRun
    b: orm.ScheduleRun
    result: comparison.Comparison


def run_view(run: orm.ScheduleRun) -> comparison.RunView:
    """Plain-data view of a run loaded by :func:`scheduling_service.get_run`."""
    rows: dict[str, list[orm.Assignment]] = {}
    for a in run.assignments:
        rows.setdefault(a.job.code, []).append(a)
    placements = {
        code: comparison.Placement(
            resource_id="+".join(sorted(r.resource.code for r in items)),
            start=items[0].start_unit,
            end=items[0].end_unit,
            tardiness=items[0].tardiness_units,
        )
        for code, items in rows.items()
    }
    metrics: Metrics | None = None
    if run.metrics is not None:
        metrics = Metrics(
            job_count=len(rows),
            on_time_count=sum(1 for items in rows.values() if items[0].tardiness_units == 0),
            on_time_rate=run.metrics.on_time_rate,
            total_tardiness=run.metrics.total_tardiness,
            weighted_tardiness=run.metrics.weighted_tardiness,
            makespan=run.metrics.makespan,
            utilization=dict(run.metrics.utilization),
            mean_delay=run.metrics.mean_delay,
        )
    return comparison.RunView(
        run_id=run.id,
        scenario_id=run.scenario_id,
        status=run.status,
        weighted=run.weighted,
        objective=run.objective_value,
        input_hash=run.input_hash,
        metrics=metrics,
        placements=placements,
        job_names={code: items[0].job.name for code, items in rows.items()},
    )


def compare_runs(session: Session, run_a_id: int, run_b_id: int) -> RunComparison:
    """Compare two runs (``b - a``). Raises ``RunNotFoundError`` if either does not exist."""
    run_a = scheduling_service.get_run(session, run_a_id)
    run_b = scheduling_service.get_run(session, run_b_id)
    return RunComparison(run_a, run_b, comparison.compare(run_view(run_a), run_view(run_b)))
