"""Translation between API schemas, ORM rows and engine models."""

from __future__ import annotations

import datetime as dt
from typing import cast

from scheduler.api import schemas
from scheduler.db import models as orm
from scheduler.engine import models as em
from scheduler.services.scheduling_service import ScenarioOverview
from scheduler.services.timeconv import unit_to_datetime


def to_problem(instance: schemas.InstanceIn) -> em.ProblemInstance:
    return em.ProblemInstance(
        horizon=instance.horizon,
        resources=tuple(
            em.Resource(r.id, r.name, tuple(em.Window(w.start, w.end) for w in r.windows))
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
            )
            for j in instance.jobs
        ),
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
            )
            for j in scenario.jobs
        ],
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
