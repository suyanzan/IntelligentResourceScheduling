"""Synthetic data endpoint."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter

from scheduler.api import convert, schemas
from scheduler.api.deps import SessionDep, SettingsDep
from scheduler.services import scheduling_service as svc
from scheduler.synthetic.generator import PRESETS, GeneratorConfig, generate
from scheduler.synthetic.opc import OPC_PRESETS, generate_opc

router = APIRouter(prefix="/api/data", tags=["synthetic data"])

# Generated data treats day 0 as a Monday; 2026-01-05 is one, so calendars line up with dates.
SYNTHETIC_HORIZON_START = dt.date(2026, 1, 5)

# Hours the lines A, B and C still need for the order they are running when an OPC plan starts.


@router.post("/generate", status_code=201)
def generate_scenario(
    body: schemas.GenerateRequest, session: SessionDep, settings: SettingsDep
) -> schemas.ScenarioDetail:
    """Create a scenario from fully fictional, seeded data (same request, same data).

    The OPC presets start today (plant time): unit 0 is midnight today, orders arrive from
    00:00, and due dates fall on today, tomorrow and the day after.
    """
    label: str
    horizon_start = SYNTHETIC_HORIZON_START
    if body.preset in OPC_PRESETS:
        local_now = dt.datetime.now(
            dt.timezone(dt.timedelta(minutes=settings.plan_utc_offset_minutes))
        )
        horizon_start = local_now.date()
        opc_config = OPC_PRESETS[body.preset]
        problem = generate_opc(opc_config)
        seed = opc_config.seed
        label = body.preset
    elif body.preset is not None:
        config = PRESETS[body.preset]
        problem = generate(config)
        seed = config.seed
        label = body.preset
    else:
        defaults = GeneratorConfig()
        config = GeneratorConfig(
            seed=defaults.seed if body.seed is None else body.seed,
            num_resources=body.num_resources or defaults.num_resources,
            num_jobs=body.num_jobs or defaults.num_jobs,
            num_days=body.num_days or defaults.num_days,
        )
        problem = generate(config)
        seed = config.seed
        label = "custom"

    scenario = svc.save_instance(
        session,
        problem,
        name=body.name or f"Synthetic {label} (seed {seed})",
        description="Fully fictional synthetic data.",
        horizon_start=horizon_start,
        time_unit_minutes=60,
        seed=seed,
    )
    session.commit()
    full = svc.get_scenario(session, scenario.id)
    return convert.scenario_detail(full, run_count=0)
