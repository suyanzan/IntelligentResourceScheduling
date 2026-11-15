"""Translation between API schemas, ORM rows and engine models."""

from __future__ import annotations

import datetime as dt
from typing import cast

from scheduler.api import schemas
from scheduler.db import models as orm
from scheduler.engine import comparison
from scheduler.engine import models as em
from scheduler.services.comparison_service import RunComparison
from scheduler.services.scheduling_service import ScenarioOverview
from scheduler.services.timeconv import unit_to_datetime


def to_problem(instance: schemas.InstanceIn) -> em.ProblemInstance:
    return em.ProblemInstance(
        horizon=instance.horizon,
        resources=tuple(
            em.Resource(
                r.id, r.name, tuple(em.Window(w.start, w.end) for w in r.windows), r.capacity
            )
            for r in instance.resources
        ),
        jobs=tuple(
            em.Job(
                id=j.id,
                name=j.name,
                duration=j.duration,
                due=j.due,
                eligible=tuple(j.eligible),
                priority=j.priority,
                release=j.release,
                work=j.work,
                after=j.after,
                cycle_limit=j.cycle_limit,
                layer=j.layer,
            )
            for j in instance.jobs
        ),
        max_merge_capacity=instance.max_merge_capacity,
        cycle_penalty=instance.cycle_penalty,
    )


def scenario_summary(
    scenario: orm.Scenario, *, resource_count: int, job_count: int, run_count: int
) -> schemas.ScenarioSummary:
    return schemas.ScenarioSummary(
        id=scenario.id,
        name=scenario.name,
        description=scenario.description,
        horizon_start=scenario.horizon_start,
        horizon_units=scenario.horizon_units,
        time_unit_minutes=scenario.time_unit_minutes,
        seed=scenario.seed,
        created_at=scenario.created_at,
        resource_count=resource_count,
        job_count=job_count,
        run_count=run_count,
    )


def overview_summary(overview: ScenarioOverview) -> schemas.ScenarioSummary:
    return scenario_summary(
        overview.scenario,
        resource_count=overview.resource_count,
        job_count=overview.job_count,
        run_count=overview.run_count,
    )


def scenario_detail(scenario: orm.Scenario, *, run_count: int) -> schemas.ScenarioDetail:
    summary = scenario_summary(
        scenario,
        resource_count=len(scenario.resources),
        job_count=len(scenario.jobs),
        run_count=run_count,
    )
    instance = schemas.InstanceOut(
        horizon=scenario.horizon_units,
        resources=[
            schemas.ResourceOut(
                id=r.code,
                name=r.name,
                windows=[schemas.WindowIn(start=w.start_unit, end=w.end_unit) for w in r.windows],
                daily_capacity_units=r.daily_capacity_units,
                capacity=r.capacity,
            )
            for r in scenario.resources
        ],
        jobs=[
            schemas.JobIn(
                id=j.code,
                name=j.name,
                duration=j.duration_units,
                due=j.due_unit,
                eligible=[r.code for r in sorted(j.eligible_resources, key=lambda r: r.id)],
                priority=j.priority,
                release=j.release_unit,
                work=j.work,
                after=j.after_code,
                cycle_limit=j.cycle_limit,
                layer=j.layer,
            )
            for j in scenario.jobs
        ],
        max_merge_capacity=scenario.max_merge_capacity,
        cycle_penalty=scenario.cycle_penalty,
    )
    return schemas.ScenarioDetail(**summary.model_dump(), instance=instance)


def _metrics(run: orm.ScheduleRun) -> schemas.MetricsOut | None:
    m = run.metrics
    if m is None:
        return None
    return schemas.MetricsOut(
        on_time_rate=m.on_time_rate,
        total_tardiness=m.total_tardiness,
        weighted_tardiness=m.weighted_tardiness,
        makespan=m.makespan,
        utilization=dict(m.utilization),
        mean_delay=m.mean_delay,
        cycle_points=m.cycle_points,
    )


def run_summary(run: orm.ScheduleRun) -> schemas.RunSummary:
    return schemas.RunSummary(
        id=run.id,
        scenario_id=run.scenario_id,
        status=cast(schemas.RunStatus, run.status),
        objective_value=run.objective_value,
        best_bound=run.best_bound,
        gap=run.gap,
        wall_time_s=run.wall_time_s,
        time_limit_s=run.time_limit_s,
        num_workers=run.num_workers,
        random_seed=run.random_seed,
        weighted=run.weighted,
        no_idle=run.no_idle,
        input_hash=run.input_hash,
        solver_version=run.solver_version,
        messages=list(run.messages),
        created_at=run.created_at,
        metrics=_metrics(run),
    )


def run_detail(run: orm.ScheduleRun) -> schemas.RunDetail:
    scenario = run.scenario

    def at(unit: int) -> dt.datetime | None:
        if scenario.horizon_start is None:
            return None
        return unit_to_datetime(scenario.horizon_start, unit, scenario.time_unit_minutes)

    assignments = [
        schemas.AssignmentOut(
            job_id=a.job.code,
            job_name=a.job.name,
            resource_id=a.resource.code,
            resource_name=a.resource.name,
            start=a.start_unit,
            end=a.end_unit,
            due=a.job.due_unit,
            priority=a.job.priority,
            tardiness=a.tardiness_units,
            delay=a.end_unit - a.job.due_unit,
            work=a.job.work,
            release=a.job.release_unit,
            layer=a.job.layer,
            cycle_limit=a.job.cycle_limit,
            over_cycle=a.job.cycle_limit is not None
            and a.end_unit - a.job.release_unit > a.job.cycle_limit,
            after=a.job.after_code,
            start_at=at(a.start_unit),
            end_at=at(a.end_unit),
        )
        for a in run.assignments
    ]
    return schemas.RunDetail(
        **run_summary(run).model_dump(),
        horizon_start=scenario.horizon_start,
        time_unit_minutes=scenario.time_unit_minutes,
        assignments=assignments,
    )


def _delta(delta: comparison.Delta) -> schemas.DeltaOut:
    return schemas.DeltaOut(a=delta.a, b=delta.b, change=delta.change)


def _placement(placement: comparison.Placement | None) -> schemas.PlacementOut | None:
    if placement is None:
        return None
    return schemas.PlacementOut(
        resource_id=placement.resource_id,
        start=placement.start,
        end=placement.end,
        tardiness=placement.tardiness,
    )


def comparison_out(compared: RunComparison) -> schemas.ComparisonOut:
    result = compared.result
    return schemas.ComparisonOut(
        a=run_summary(compared.a),
        b=run_summary(compared.b),
        same_scenario=result.same_scenario,
        same_inputs=result.same_inputs,
        objective_comparable=result.objective_comparable,
        better=result.better,
        metrics={key: _delta(value) for key, value in result.metrics.items()},
        utilization={key: _delta(value) for key, value in result.utilization.items()},
        jobs=[
            schemas.JobDiffOut(
                job_id=job.job_id,
                job_name=job.job_name,
                a=_placement(job.a),
                b=_placement(job.b),
                moved=job.moved,
                tardiness_change=job.tardiness_change,
            )
            for job in result.jobs
        ],
        moved_jobs=result.moved_jobs,
        notes=list(result.notes),
    )


# --- production floor ------------------------------------------------------------------------


def plan_detail(
    plan: orm.ReleasedPlan, *, utc_offset_minutes: int, now: dt.datetime
) -> schemas.PlanOut:
    """A released plan with planned times in plant-local time and what really happened."""
    scenario = plan.scenario
    tz = dt.timezone(dt.timedelta(minutes=utc_offset_minutes))
    start_date = scenario.horizon_start
    assert start_date is not None  # guaranteed when the plan was released

    def at(unit: int) -> dt.datetime:
        return unit_to_datetime(start_date, unit, scenario.time_unit_minutes).replace(tzinfo=tz)

    placed: dict[int, list[orm.Assignment]] = {}
    for a in plan.run.assignments:
        placed.setdefault(a.job_id, []).append(a)

    lines = {a.resource.code: a.resource for a in plan.run.assignments}
    jobs: list[schemas.FloorJobOut] = []
    for actual in plan.actuals:
        rows = placed.get(actual.job_id, [])
        if not rows:
            continue
        job = actual.job
        first = rows[0]
        jobs.append(
            schemas.FloorJobOut(
                id=job.code,
                name=job.name,
                layer=job.layer,
                priority=job.priority,
                work=job.work,
                after=job.after_code,
                cycle_limit_minutes=(
                    None
                    if job.cycle_limit is None
                    else job.cycle_limit * scenario.time_unit_minutes
                ),
                due_at=at(job.due_unit),
                planned_start_at=at(first.start_unit),
                planned_end_at=at(first.end_unit),
                lines=sorted(r.resource.code for r in rows),
                status=actual.status,  # type: ignore[arg-type]
                actual_start_at=actual.actual_start,
                actual_end_at=actual.actual_end,
                note=actual.note,
                updated_by=actual.updated_by,
                updated_at=actual.updated_at,
            )
        )
    jobs.sort(key=lambda j: (j.planned_start_at, j.id))
    return schemas.PlanOut(
        id=plan.id,
        active=plan.active,
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        run_id=plan.run_id,
        released_at=plan.released_at,
        released_by=plan.released_by,
        note=plan.note,
        utc_offset_minutes=utc_offset_minutes,
        time_unit_minutes=scenario.time_unit_minutes,
        server_time=now,
        lines=[
            schemas.FloorLineOut(id=code, name=r.name, capacity=r.capacity)
            for code, r in sorted(lines.items())
        ],
        jobs=jobs,
    )


def event_out(event: orm.PlanEvent) -> schemas.EventOut:
    return schemas.EventOut(
        id=event.id,
        job_id=event.job.code,
        job_name=event.job.name,
        action=event.action,
        actor=event.actor,
        recorded_at=event.recorded_at,
        effective_at=event.effective_at,
        note=event.note,
    )
