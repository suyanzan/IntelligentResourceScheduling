"""Releasing a solved run to the production floor and recording what really happens.

Like the scheduling service, functions flush but never commit; the caller owns the transaction.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session, selectinload

from scheduler.db import models as orm
from scheduler.services import floor_rules as rules
from scheduler.services.errors import PlanError, PlanNotFoundError, RunNotFoundError

RELEASABLE_STATUSES = ("OPTIMAL", "FEASIBLE")
ACTIONS = ("start", "complete", "revert", "note")


def _plan_query() -> Select[tuple[orm.ReleasedPlan]]:
    return select(orm.ReleasedPlan).options(
        selectinload(orm.ReleasedPlan.scenario),
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

    session.execute(
        update(orm.ReleasedPlan).where(orm.ReleasedPlan.active.is_(True)).values(active=False)
    )
    plan = orm.ReleasedPlan(
        scenario_id=run.scenario_id, run_id=run.id, released_by=released_by, note=note, active=True
    )
    for job_id in sorted({a.job_id for a in run.assignments}):
        plan.actuals.append(orm.JobActual(job_id=job_id))
    session.add(plan)
    session.flush()
    return get_plan(session, plan.id)


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
