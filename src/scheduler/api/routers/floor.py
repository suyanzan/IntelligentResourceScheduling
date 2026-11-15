"""Production floor endpoints: release a run, follow the plan, record what really happened."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from scheduler.api import convert, schemas
from scheduler.api.deps import SessionDep, SettingsDep
from scheduler.db import models as orm
from scheduler.services import floor_demo, scheduling_service
from scheduler.services import floor_service as svc

router = APIRouter(prefix="/api/floor", tags=["production floor"])


def _out(plan: orm.ReleasedPlan, settings: SettingsDep) -> schemas.PlanOut:
    return convert.plan_detail(
        plan,
        utc_offset_minutes=settings.plan_utc_offset_minutes,
        now=dt.datetime.now(dt.UTC),
    )


@router.post("/plans", status_code=201)
def release(
    body: schemas.ReleaseRequest, session: SessionDep, settings: SettingsDep
) -> schemas.PlanOut:
    """Hand a solved run to the floor. Replaces the plan that was active."""
    plan = svc.release_run(session, body.run_id, released_by=body.released_by, note=body.note)
    session.commit()
    return _out(svc.get_plan(session, plan.id), settings)


@router.get("/plan")
def current_plan(session: SessionDep, settings: SettingsDep) -> schemas.PlanOut:
    """The plan the floor is working from (404 when nothing has been released)."""
    return _out(svc.get_active_plan(session), settings)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, session: SessionDep, settings: SettingsDep) -> schemas.PlanOut:
    return _out(svc.get_plan(session, plan_id), settings)


@router.get("/plans/{plan_id}/events")
def events(
    plan_id: int, session: SessionDep, limit: int = Query(default=50, ge=1, le=500)
) -> list[schemas.EventOut]:
    return [convert.event_out(e) for e in svc.list_events(session, plan_id, limit)]


@router.post("/plans/{plan_id}/jobs/{job_id}/start")
def start_job(
    plan_id: int,
    job_id: str,
    session: SessionDep,
    settings: SettingsDep,
    body: schemas.StartRequest | None = None,
) -> schemas.PlanOut:
    request = body or schemas.StartRequest()
    plan = svc.record_action(
        session, plan_id, job_id, "start", at=request.at, actor=request.by, note=request.note
    )
    session.commit()
    return _out(plan, settings)


@router.post("/plans/{plan_id}/jobs/{job_id}/complete")
def complete_job(
    plan_id: int,
    job_id: str,
    session: SessionDep,
    settings: SettingsDep,
    body: schemas.CompleteRequest | None = None,
) -> schemas.PlanOut:
    request = body or schemas.CompleteRequest()
    plan = svc.record_action(
        session,
        plan_id,
        job_id,
        "complete",
        at=request.at,
        started_at=request.started_at,
        actor=request.by,
        note=request.note,
    )
    session.commit()
    return _out(plan, settings)


@router.post("/plans/{plan_id}/jobs/{job_id}/revert")
def revert_job(
    plan_id: int,
    job_id: str,
    session: SessionDep,
    settings: SettingsDep,
    body: schemas.RevertRequest | None = None,
) -> schemas.PlanOut:
    request = body or schemas.RevertRequest()
    plan = svc.record_action(session, plan_id, job_id, "revert", actor=request.by)
    session.commit()
    return _out(plan, settings)


@router.post("/plans/{plan_id}/jobs/{job_id}/note")
def note_job(
    plan_id: int,
    job_id: str,
    body: schemas.NoteRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> schemas.PlanOut:
    plan = svc.record_action(session, plan_id, job_id, "note", actor=body.by, note=body.note)
    session.commit()
    return _out(plan, settings)


@router.post("/plans/{plan_id}/simulate")
def simulate_shift(plan_id: int, session: SessionDep, settings: SettingsDep) -> schemas.PlanOut:
    """Demo only: record a plausible duty shift up to now for orders not yet started."""
    now = dt.datetime.now(dt.UTC)
    current = _out(svc.get_plan(session, plan_id), settings)
    jobs = [
        floor_demo.DemoJob(
            id=j.id,
            planned_start=j.planned_start_at,
            planned_end=j.planned_end_at,
            due=j.due_at,
            lines=tuple(j.lines),
            after=j.after,
            status=j.status,
            actual_start=j.actual_start_at,
            actual_end=j.actual_end_at,
        )
        for j in current.jobs
    ]
    for step in floor_demo.plan_shift(jobs, now, seed=plan_id):
        svc.record_action(
            session,
            plan_id,
            step.job_id,
            "start",
            at=step.start,
            actor="Demo engineer",
            note=step.note,
            now=now,
        )
        if step.end is not None:
            svc.record_action(
                session,
                plan_id,
                step.job_id,
                "complete",
                at=step.end,
                actor="Demo engineer",
                now=now,
            )
    session.commit()
    return _out(svc.get_plan(session, plan_id), settings)


@router.post("/plans/{plan_id}/replan", status_code=201)
def replan(plan_id: int, session: SessionDep, settings: SettingsDep) -> schemas.ScenarioDetail:
    """A scenario with what is left of the plan, from now and from what really happened.

    Solve it, check the result, then release it: finished and running orders stay on the floor.
    """
    scenario = svc.create_replan(
        session,
        plan_id,
        now=dt.datetime.now(dt.UTC),
        utc_offset_minutes=settings.plan_utc_offset_minutes,
    )
    session.commit()
    return convert.scenario_detail(
        scheduling_service.get_scenario(session, scenario.id), run_count=0
    )
