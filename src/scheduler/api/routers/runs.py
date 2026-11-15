"""Run endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from scheduler.api import convert, schemas
from scheduler.api.deps import SessionDep
from scheduler.services import scheduling_service as svc

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/{run_id}")
def get_run(run_id: int, session: SessionDep) -> schemas.RunDetail:
    return convert.run_detail(svc.get_run(session, run_id))
