"""Releasing a solved run to the production floor and recording what really happens.

Like the scheduling service, functions flush but never commit; the caller owns the transaction.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session, selectinload

from scheduler.db import models as orm
from scheduler.services import floor_rules as rules
from scheduler.services import replan_rules, scheduling_service
from scheduler.services.errors import (
    InvalidInstanceError,
    PlanError,
    PlanNotFoundError,
    RunNotFoundError,
)

RELEASABLE_STATUSES = ("OPTIMAL", "FEASIBLE")
ACTIONS = ("start", "complete", "revert", "note")


def _plan_query() -> Select[orm.ReleasedPlan]:
    return select(orm.ReleasedPlan).options(
        selectinload(orm.ReleasedPlan.scenario).selectinload(orm.Scenario.resources),
        selectinload(orm.ReleasedPlan.actuals).selectinload(orm.JobActual.job),
        selectinload(orm.ReleasedPlan.run)
        .selectinload(orm.ScheduleRun.assignments)
        .selectinload(orm.Assignment.job),
        selectinload(orm.ReleasedPlan.run)
        .selectinload(orm.ScheduleRun.assignments)
        .selectinload(orm.Assignment.resource),
    )


def release_run(
    session: Session, run_id: int, *, released_by: str = "", note: str = ""
) -> orm.ReleasedPlan:
    """Hand a solved run to the floor. Any plan that was active is retired."""
    run = session.scalars(
        select(orm.ScheduleRun)
        .where(orm.ScheduleRun.id == run_id)
        .options(selectinload(orm.ScheduleRun.assignments), selectinload(orm.ScheduleRun.scenario))
    ).one_or_none()
    if run is None:
        raise RunNotFoundError(run_id)
    if run.status not in RELEASABLE_STATUSES or not run.assignments:
        raise PlanError("this run has no schedule to release; solve the scenario first")
    if run.scenario.horizon_start is None:
        raise PlanError("the scenario has no start date, so planned times cannot be shown")

    previous = session.scalars(
        _plan_query()
        .where(orm.ReleasedPlan.active.is_(True))
        .order_by(orm.ReleasedPlan.id.desc())
        .limit(1)
    ).one_or_none()
    session.execute(
        update(orm.ReleasedPlan).where(orm.ReleasedPlan.active.is_(True)).values(active=False)
    )
    plan = orm.ReleasedPlan(
        scenario_id=run.scenario_id, run_id=run.id, released_by=released_by, note=note, active=True
    )
    for job_id in sorted({a.job_id for a in run.assignments}):
        plan.actuals.append(orm.JobActual(job_id=job_id))
    if previous is not None and run.scenario.source_plan_id == previous.id:
        plan.actuals.extend(_carried_over(previous))
    session.add(plan)
    session.flush()
    return get_plan(session, plan.id)


def _carried_over(previous: orm.ReleasedPlan) -> list[orm.JobActual]:
    """Finished and running jobs of the plan being replaced, with where it had placed them."""
    placed: dict[int, list[orm.Assignment]] = {}
    for a in previous.run.assignments:
        placed.setdefault(a.job_id, []).append(a)
    carried: list[orm.JobActual] = []
    for actual in previous.actuals:
        if actual.status == "planned":
            continue
        rows = placed.get(actual.job_id)
        if rows:
            start, end = rows[0].start_unit, rows[0].end_unit
            lines = ",".join(sorted(r.resource.code for r in rows))
            due = actual.job.due_unit
        elif actual.carried_start_unit is not None and actual.carried_end_unit is not None:
            start, end = actual.carried_start_unit, actual.carried_end_unit
            lines = actual.carried_lines or ""
            due = actual.carried_due_unit if actual.carried_due_unit is not None else 0
        else:  # pragma: no cover - a started job always has a placement
            continue
        carried.append(
            orm.JobActual(
                job_id=actual.job_id,
                status=actual.status,
                actual_start=actual.actual_start,
                actual_end=actual.actual_end,
                note=actual.note,
                updated_by=actual.updated_by,
                carried_start_unit=start,
                carried_end_unit=end,
                carried_due_unit=due,
                carried_lines=lines,
            )
        )
    return carried


def create_replan(
    session: Session, plan_id: int, *, now: dt.datetime, utc_offset_minutes: int
) -> orm.Scenario:
    """A new scenario holding what is left of the active plan, to be solved and released."""
    plan = get_plan(session, plan_id)
    if not plan.active:
        raise PlanError("only the plan the floor is working from can be re-planned")
    scenario = plan.scenario
    start_date = scenario.horizon_start
    if start_date is None:  # pragma: no cover - guaranteed when the plan was released
        raise PlanError("the scenario has no start date")
    unit_minutes = scenario.time_unit_minutes
    origin = dt.datetime.combine(start_date, dt.time.min, tzinfo=dt.UTC) - dt.timedelta(
        minutes=utc_offset_minutes
    )

    def units(when: dt.datetime) -> float:
        return (when - origin).total_seconds() / 60 / unit_minutes

    placed: dict[int, list[orm.Assignment]] = {}
    for a in plan.run.assignments:
        placed.setdefault(a.job_id, []).append(a)
    progress: dict[str, replan_rules.Progress] = {}
    for actual in plan.actuals:
        rows = placed.get(actual.job_id)
        if rows:
            length = rows[0].end_unit - rows[0].start_unit
            lines = tuple(sorted(r.resource.code for r in rows))
        else:
            length = (actual.carried_end_unit or 0) - (actual.carried_start_unit or 0)
            lines = tuple(x for x in (actual.carried_lines or "").split(",") if x)
        progress[actual.job.code] = replan_rules.Progress(
            status=actual.status,
            start_unit=None if actual.actual_start is None else units(actual.actual_start),
            planned_units=length,
            lines=lines,
        )

    problem = scheduling_service.load_instance(session, scenario.id)
    now_unit = int(-(-units(now) // 1))  # round up to the next unit boundary
    try:
        remaining = replan_rules.remaining_problem(problem, progress, max(0, now_unit))
        base = scenario.name.split(" · replan")[0]
        local = now + dt.timedelta(minutes=utc_offset_minutes)
        created = scheduling_service.save_instance(
            session,
            remaining,
            name=f"{base} · replan {local:%H:%M}",
            description=f"Re-planned from plan #{plan.id} at {local:%a %d %b %H:%M}.",
            horizon_start=start_date,
            time_unit_minutes=unit_minutes,
            seed=scenario.seed,
        )
    except (replan_rules.ReplanError, InvalidInstanceError) as error:
        raise PlanError(f"cannot re-plan: {error}") from error
    created.source_plan_id = plan.id
    session.flush()
    return created


def get_plan(session: Session, plan_id: int) -> orm.ReleasedPlan:
    plan = session.scalars(
        _plan_query()
        .where(orm.ReleasedPlan.id == plan_id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if plan is None:
        raise PlanNotFoundError(f"plan {plan_id} not found")
    return plan


def get_active_plan(session: Session) -> orm.ReleasedPlan:
    """The plan the floor is working from (the latest release)."""
    plan = session.scalars(
        _plan_query()
        .where(orm.ReleasedPlan.active.is_(True))
        .order_by(orm.ReleasedPlan.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if plan is None:
        raise PlanNotFoundError()
    return plan


def record_action(
    session: Session,
    plan_id: int,
    job_code: str,
    action: str,
    *,
    at: dt.datetime | None = None,
    started_at: dt.datetime | None = None,
    actor: str = "",
    note: str | None = None,
    now: dt.datetime | None = None,
) -> orm.ReleasedPlan:
    """Apply one floor update to a job of a plan and return the refreshed plan."""
    if action not in ACTIONS:
        raise PlanError(f"unknown action {action!r}")
    now = now or dt.datetime.now(dt.UTC)
    plan = get_plan(session, plan_id)
    if not plan.active:
        raise PlanError("this plan has been replaced by a newer release and is read-only")
    row = next((a for a in plan.actuals if a.job.code == job_code), None)
    if row is None:
        raise PlanNotFoundError(f"job {job_code!r} is not part of plan {plan_id}")

    state = rules.Actual(row.status, row.actual_start, row.actual_end)
    effective = at or now
    if action == "start":
        state = rules.start_job(state, at=effective, now=now)
    elif action == "complete":
        state = rules.complete_job(state, at=effective, now=now, started_at=started_at)
    elif action == "revert":
        state = rules.revert_job(state)

    row.status, row.actual_start, row.actual_end = state.status, state.start, state.end
    if note is not None:
        row.note = note
    row.updated_by = actor
    session.add(
        orm.PlanEvent(
            plan_id=plan.id,
            job_id=row.job_id,
            action=action,
            actor=actor,
            effective_at=effective if action in ("start", "complete") else None,
            note=note or "",
        )
    )
    session.flush()
    session.expire(row, ["updated_at"])
    return get_plan(session, plan_id)


def list_events(session: Session, plan_id: int, limit: int = 50) -> list[orm.PlanEvent]:
    get_plan(session, plan_id)
    return list(
        session.scalars(
            select(orm.PlanEvent)
            .where(orm.PlanEvent.plan_id == plan_id)
            .options(selectinload(orm.PlanEvent.job))
            .order_by(orm.PlanEvent.id.desc())
            .limit(limit)
        )
    )
