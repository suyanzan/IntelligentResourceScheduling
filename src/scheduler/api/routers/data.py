"""Synthetic data endpoint."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter

from scheduler.api import convert, schemas
from scheduler.api.deps import SessionDep
from scheduler.services import scheduling_service as svc
from scheduler.synthetic.generator import PRESETS, GeneratorConfig, generate

router = APIRouter(prefix="/api/data", tags=["synthetic data"])

# Generated data treats day 0 as a Monday; 2026-01-05 is one, so calendars line up with dates.
SYNTHETIC_HORIZON_START = dt.date(2026, 1, 5)


@router.post("/generate", status_code=201)
def generate_scenario(body: schemas.GenerateRequest, session: SessionDep) -> schemas.ScenarioDetail:
    """Create a scenario from fully fictional, seeded data (same request, same data)."""
    if body.preset is not None:
        config = PRESETS[body.preset]
        label = body.preset
    else:
        defaults = GeneratorConfig()
        config = GeneratorConfig(
            seed=defaults.seed if body.seed is None else body.seed,
            num_resources=body.num_resources or defaults.num_resources,
            num_jobs=body.num_jobs or defaults.num_jobs,
            num_days=body.num_days or defaults.num_days,
        )
        label = "custom"

    scenario = svc.save_instance(
        session,
        generate(config),
        name=body.name or f"Synthetic {label} (seed {config.seed})",
        description="Fully fictional synthetic data.",
        horizon_start=SYNTHETIC_HORIZON_START,
        time_unit_minutes=60,
        seed=config.seed,
    )
    session.commit()
    full = svc.get_scenario(session, scenario.id)
    return convert.scenario_detail(full, run_count=0)
