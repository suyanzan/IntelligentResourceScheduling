"""Scheduling service: persists scenarios and runs and drives the optimization engine.

This is the only layer that translates between database rows (:mod:`scheduler.db.models`) and
engine types (:mod:`scheduler.engine.models`). Functions flush but never commit; the caller owns
the transaction (see :func:`scheduler.db.session.session_scope`).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from importlib.metadata import version

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from scheduler.db import models as orm
from scheduler.engine import models as em
from scheduler.engine.metrics import compute_metrics, daily_capacity, tardiness
from scheduler.engine.serialization import instance_hash
from scheduler.engine.solver import solve
from scheduler.engine.validation import validate_instance
from scheduler.services.errors import (
    InvalidInstanceError,
    RunNotFoundError,
    ScenarioLockedError,
    ScenarioNotFoundError,
)

MINUTES_PER_DAY = 1440


@dataclass(frozen=True, slots=True)
class ScenarioOverview:
    """A scenario row with the counts needed for list views."""

    scenario: orm.Scenario
    resource_count: int
    job_count: int
    run_count: int


def save_instance(
    session: Session,
    problem: em.ProblemInstance,
    *,
    name: str,
    description: str = "",
    horizon_start: dt.date | None = None,
    time_unit_minutes: int = 60,
    seed: int | None = None,
) -> orm.Scenario:
    """Validate ``problem`` and store it as a new scenario."""
    _check_instance(problem)
    if not 1 <= time_unit_minutes <= MINUTES_PER_DAY:
        raise ValueError(f"time_unit_minutes must be between 1 and {MINUTES_PER_DAY}")

    scenario = orm.Scenario(
        name=name,
        description=description,
        horizon_start=horizon_start,
        horizon_units=problem.horizon,
        time_unit_minutes=time_unit_minutes,
        seed=seed,
    )
    session.add(scenario)
    _populate(scenario, problem)
    session.flush()
    return scenario


def load_instance(session: Session, scenario_id: int) -> em.ProblemInstance:
    """Rebuild the engine problem for a scenario.

    Each job's eligible resources are returned in resource creation order.
    """
    return _to_instance(_get_scenario(session, scenario_id))


def replace_instance(session: Session, scenario_id: int, problem: em.ProblemInstance) -> None:
    """Replace a scenario's resources and jobs. Refused once the scenario has runs."""
    _check_instance(problem)
    scenario = _get_scenario(session, scenario_id)
    if scenario_has_runs(session, scenario_id):
        raise ScenarioLockedError(scenario_id)

    session.execute(delete(orm.Job).where(orm.Job.scenario_id == scenario_id))
    session.execute(delete(orm.Resource).where(orm.Resource.scenario_id == scenario_id))
    session.expire_all()

    scenario.horizon_units = problem.horizon
    _populate(scenario, problem)
    session.flush()


def clone_scenario(session: Session, scenario_id: int, *, name: str) -> orm.Scenario:
    """Copy a scenario's inputs (not its runs) into a new, editable scenario."""
    source = _get_scenario(session, scenario_id)
    return save_instance(
        session,
        _to_instance(source),
        name=name,
        description=source.description,
        horizon_start=source.horizon_start,
        time_unit_minutes=source.time_unit_minutes,
        seed=source.seed,
    )


def delete_scenario(session: Session, scenario_id: int) -> None:
    """Delete a scenario with all its inputs, runs, assignments and metrics."""
    _get_scenario(session, scenario_id)
    session.execute(delete(orm.Scenario).where(orm.Scenario.id == scenario_id))
    session.expire_all()


def get_scenario(session: Session, scenario_id: int) -> orm.Scenario:
    """A scenario with its resources, windows, jobs and eligibility loaded."""
    return _get_scenario(session, scenario_id)


def list_scenarios(session: Session) -> list[ScenarioOverview]:
    """All scenarios, newest first, with resource/job/run counts."""
    resources = (
        select(func.count(orm.Resource.id))
        .where(orm.Resource.scenario_id == orm.Scenario.id)
        .correlate(orm.Scenario)
        .scalar_subquery()
    )
    jobs = (
        select(func.count(orm.Job.id))
        .where(orm.Job.scenario_id == orm.Scenario.id)
        .correlate(orm.Scenario)
        .scalar_subquery()
    )
    runs = (
        select(func.count(orm.ScheduleRun.id))
        .where(orm.ScheduleRun.scenario_id == orm.Scenario.id)
        .correlate(orm.Scenario)
        .scalar_subquery()
    )
    rows = session.execute(
        select(orm.Scenario, resources, jobs, runs).order_by(orm.Scenario.id.desc())
    ).all()
    return [ScenarioOverview(sc, int(r), int(j), int(n)) for sc, r, j, n in rows]


def count_runs(session: Session, scenario_id: int) -> int:
    return int(
        session.scalar(
            select(func.count(orm.ScheduleRun.id)).where(
                orm.ScheduleRun.scenario_id == scenario_id
            )
        )
        or 0
    )


def list_runs(session: Session, scenario_id: int) -> list[orm.ScheduleRun]:
    """A scenario's runs, newest first, with metrics loaded."""
    if session.get(orm.Scenario, scenario_id) is None:
        raise ScenarioNotFoundError(scenario_id)
    return list(
        session.scalars(
            select(orm.ScheduleRun)
            .where(orm.ScheduleRun.scenario_id == scenario_id)
            .options(selectinload(orm.ScheduleRun.metrics))
            .order_by(orm.ScheduleRun.id.desc())
        )
    )


def get_run(session: Session, run_id: int) -> orm.ScheduleRun:
    """A run with metrics, assignments (and their jobs and resources) and scenario loaded."""
    run = session.scalars(
        select(orm.ScheduleRun)
        .where(orm.ScheduleRun.id == run_id)
        .options(
            selectinload(orm.ScheduleRun.metrics),
            selectinload(orm.ScheduleRun.assignments).selectinload(orm.Assignment.job),
            selectinload(orm.ScheduleRun.assignments).selectinload(orm.Assignment.resource),
            selectinload(orm.ScheduleRun.scenario),
        )
        .execution_options(populate_existing=True)
    ).one_or_none()
    if run is None:
        raise RunNotFoundError(run_id)
    return run


def scenario_has_runs(session: Session, scenario_id: int) -> bool:
    found = session.scalar(
        select(orm.ScheduleRun.id).where(orm.ScheduleRun.scenario_id == scenario_id).limit(1)
    )
    return found is not None


def solve_scenario(
    session: Session, scenario_id: int, params: em.SolveParams | None = None
) -> orm.ScheduleRun:
    """Solve a scenario and persist the outcome as an immutable run.

    Any status is persisted (including INFEASIBLE, UNKNOWN and MODEL_INVALID, with the solver's
    messages). If the engine's own verification fails it raises and nothing is stored.
    """
    params = params or em.SolveParams()
    scenario = _get_scenario(session, scenario_id)
    problem = _to_instance(scenario)
    result = solve(problem, params)

    run = orm.ScheduleRun(
        scenario_id=scenario.id,
        status=result.status.value,
        objective_value=result.objective,
        best_bound=result.best_bound,
        gap=result.gap,
        wall_time_s=result.wall_time_s,
        time_limit_s=params.time_limit_s,
        num_workers=params.num_workers,
        random_seed=params.random_seed,
        weighted=params.weighted,
        no_idle=params.no_idle,
        input_hash=instance_hash(problem),
        solver_version=version("ortools"),
        messages=list(result.messages),
    )

    if result.assignments:
        job_ids = {job.code: job.id for job in scenario.jobs}
        resource_ids = {resource.code: resource.id for resource in scenario.resources}
        jobs = problem.job_by_id()
        for a in result.assignments:
            run.assignments.append(
                orm.Assignment(
                    job_id=job_ids[a.job_id],
                    resource_id=resource_ids[a.resource_id],
                    start_unit=a.start,
                    end_unit=a.end,
                    tardiness_units=tardiness(jobs[a.job_id], a.end),
                )
            )
        metrics = compute_metrics(problem, result.assignments)
        run.metrics = orm.RunMetrics(
            on_time_rate=metrics.on_time_rate,
            total_tardiness=metrics.total_tardiness,
            weighted_tardiness=metrics.weighted_tardiness,
            makespan=metrics.makespan,
            utilization=metrics.utilization,
            mean_delay=metrics.mean_delay,
        )

    session.add(run)
    session.flush()
    return run


def load_run_assignments(session: Session, run_id: int) -> tuple[em.Assignment, ...]:
    """A run's schedule as engine assignments (job and resource codes, not row ids)."""
    if session.get(orm.ScheduleRun, run_id) is None:
        raise RunNotFoundError(run_id)
    rows = session.execute(
        select(
            orm.Job.code,
            orm.Resource.code,
            orm.Assignment.start_unit,
            orm.Assignment.end_unit,
        )
        .join(orm.Job, orm.Job.id == orm.Assignment.job_id)
        .join(orm.Resource, orm.Resource.id == orm.Assignment.resource_id)
        .where(orm.Assignment.run_id == run_id)
        .order_by(orm.Assignment.id)
    ).all()
    return tuple(em.Assignment(job, resource, start, end) for job, resource, start, end in rows)


# --- internals ---------------------------------------------------------------------------------


def _check_instance(problem: em.ProblemInstance) -> None:
    issues = validate_instance(problem)
    if issues:
        raise InvalidInstanceError(issues)


def _get_scenario(session: Session, scenario_id: int) -> orm.Scenario:
    scenario = session.scalars(
        select(orm.Scenario)
        .where(orm.Scenario.id == scenario_id)
        .options(
            selectinload(orm.Scenario.resources).selectinload(orm.Resource.windows),
            selectinload(orm.Scenario.jobs).selectinload(orm.Job.eligible_resources),
        )
        .execution_options(populate_existing=True)
    ).one_or_none()
    if scenario is None:
        raise ScenarioNotFoundError(scenario_id)
    return scenario


def _populate(scenario: orm.Scenario, problem: em.ProblemInstance) -> None:
    units_per_day = MINUTES_PER_DAY // scenario.time_unit_minutes
    rows: dict[str, orm.Resource] = {}
    for resource in problem.resources:
        row = orm.Resource(
            code=resource.id,
            name=resource.name,
            daily_capacity_units=daily_capacity(resource.windows, units_per_day),
            capacity=resource.capacity,
        )
        row.windows = [
            orm.ResourceWindow(start_unit=w.start, end_unit=w.end) for w in resource.windows
        ]
        scenario.resources.append(row)
        rows[resource.id] = row

    for job in problem.jobs:
        job_row = orm.Job(
            code=job.id,
            name=job.name,
            duration_units=job.duration,
            due_unit=job.due,
            priority=job.priority,
            release_unit=job.release,
            work=job.work,
        )
        job_row.eligible_resources = [rows[resource_id] for resource_id in job.eligible]
        scenario.jobs.append(job_row)


def _to_instance(scenario: orm.Scenario) -> em.ProblemInstance:
    resources = tuple(
        em.Resource(
            id=row.code,
            name=row.name,
            windows=tuple(em.Window(w.start_unit, w.end_unit) for w in row.windows),
            capacity=row.capacity,
        )
        for row in scenario.resources
    )
    jobs = tuple(
        em.Job(
            id=row.code,
            name=row.name,
            duration=row.duration_units,
            due=row.due_unit,
            eligible=tuple(r.code for r in sorted(row.eligible_resources, key=lambda r: r.id)),
            priority=row.priority,
            release=row.release_unit,
            work=row.work,
        )
        for row in scenario.jobs
    )
    return em.ProblemInstance(horizon=scenario.horizon_units, resources=resources, jobs=jobs)
