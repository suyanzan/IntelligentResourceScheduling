"""Scenario endpoints: CRUD, clone, replace inputs, solve and list runs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from scheduler.api import convert, schemas
from scheduler.api.deps import SessionDep, SettingsDep
from scheduler.engine.models import SolveParams
from scheduler.services import scheduling_service as svc

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _detail(session: SessionDep, scenario_id: int) -> schemas.ScenarioDetail:
    scenario = svc.get_scenario(session, scenario_id)
    return convert.scenario_detail(scenario, run_count=svc.count_runs(session, scenario_id))


@router.get("")
def list_scenarios(session: SessionDep) -> list[schemas.ScenarioSummary]:
    return [convert.overview_summary(o) for o in svc.list_scenarios(session)]


@router.post("", status_code=201)
def create_scenario(body: schemas.ScenarioCreate, session: SessionDep) -> schemas.ScenarioDetail:
    scenario = svc.save_instance(
        session,
        convert.to_problem(body.instance),
        name=body.name,
        description=body.description,
        horizon_start=body.horizon_start,
        time_unit_minutes=body.time_unit_minutes,
        seed=body.seed,
    )
    session.commit()
    return _detail(session, scenario.id)


@router.get("/{scenario_id}")
def get_scenario(scenario_id: int, session: SessionDep) -> schemas.ScenarioDetail:
    return _detail(session, scenario_id)


@router.delete("/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: int, session: SessionDep) -> Response:
    svc.delete_scenario(session, scenario_id)
    session.commit()
    return Response(status_code=204)


@router.post("/{scenario_id}/clone", status_code=201)
def clone_scenario(
    scenario_id: int, body: schemas.CloneRequest, session: SessionDep
) -> schemas.ScenarioDetail:
    clone = svc.clone_scenario(session, scenario_id, name=body.name)
    session.commit()
    return _detail(session, clone.id)


@router.put("/{scenario_id}/instance")
def replace_instance(
    scenario_id: int, body: schemas.InstanceIn, session: SessionDep
) -> schemas.ScenarioDetail:
    """Replace resources and jobs. Returns 409 once the scenario has runs; clone it instead."""
    svc.replace_instance(session, scenario_id, convert.to_problem(body))
    session.commit()
    return _detail(session, scenario_id)


@router.post("/{scenario_id}/solve", status_code=201)
def solve_scenario(
    scenario_id: int,
    session: SessionDep,
    settings: SettingsDep,
    body: schemas.SolveRequest | None = None,
) -> schemas.RunDetail:
    """Solve synchronously and store the outcome as a new run.

    The request blocks until the solver finishes or ``time_limit_s`` elapses. Any status is a
    successful request (201); inspect ``status``, ``gap`` and ``messages`` in the response.
    """
    request = body or schemas.SolveRequest()
    if request.time_limit_s > settings.max_time_limit_s:
        raise HTTPException(
            status_code=422,
            detail=f"time_limit_s may not exceed {settings.max_time_limit_s:g} seconds",
        )
    params = SolveParams(
        time_limit_s=request.time_limit_s,
        num_workers=request.num_workers,
        random_seed=request.random_seed,
        weighted=request.weighted,
        no_idle=request.no_idle,
    )
    run = svc.solve_scenario(session, scenario_id, params)
    session.commit()
    return convert.run_detail(svc.get_run(session, run.id))


@router.get("/{scenario_id}/runs")
def list_runs(scenario_id: int, session: SessionDep) -> list[schemas.RunSummary]:
    return [convert.run_summary(r) for r in svc.list_runs(session, scenario_id)]
