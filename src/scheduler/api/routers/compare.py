"""Run comparison endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from scheduler.api import convert, schemas
from scheduler.api.deps import SessionDep
from scheduler.services import comparison_service

router = APIRouter(prefix="/api/compare", tags=["compare"])


@router.get("")
def compare_runs(
    session: SessionDep,
    run_a: Annotated[int, Query(ge=1, description="Baseline run.")],
    run_b: Annotated[int, Query(ge=1, description="Run to compare with the baseline.")],
) -> schemas.ComparisonOut:
    """KPI, utilization and per-job differences between two runs (all changes are b - a)."""
    return convert.comparison_out(comparison_service.compare_runs(session, run_a, run_b))
