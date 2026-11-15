import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scheduler.db import models as orm
from scheduler.engine.metrics import daily_capacity
from scheduler.engine.models import Job, ProblemInstance, Resource, Window
from scheduler.engine.serialization import instance_hash
from scheduler.services import scheduling_service as svc
from scheduler.services.errors import (
    InvalidInstanceError,
    RunNotFoundError,
    ScenarioLockedError,
    ScenarioNotFoundError,
)
from scheduler.synthetic.generator import PRESETS, preset


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_round_trip_preserves_the_instance(session: Session, name: str) -> None:
    problem = preset(name)
    scenario = svc.save_instance(session, problem, name=name)
    session.expire_all()
    loaded = svc.load_instance(session, scenario.id)
    assert instance_hash(loaded) == instance_hash(problem)
    assert loaded == problem


def test_scenario_metadata_and_derived_capacity(session: Session) -> None:
    problem = preset("tiny")
    scenario = svc.save_instance(
        session,
        problem,
        name="Demo",
        description="synthetic",
        horizon_start=dt.date(2026, 1, 5),
        time_unit_minutes=60,
        seed=1,
    )
    session.expire_all()
    row = session.get(orm.Scenario, scenario.id)
    assert row is not None
    assert (row.name, row.description, row.seed) == ("Demo", "synthetic", 1)
    assert row.horizon_start == dt.date(2026, 1, 5)
    assert row.horizon_units == problem.horizon
    assert row.time_unit_minutes == 60

    by_code = {r.code: r for r in row.resources}
    for resource in problem.resources:
        assert by_code[resource.id].daily_capacity_units == daily_capacity(resource.windows, 24)


def test_save_rejects_invalid_instances(session: Session) -> None:
    bad = ProblemInstance(
        horizon=10,
        resources=(Resource("R1", "a", (Window(0, 10),)),),
        jobs=(Job("J1", "a", duration=3, due=5, eligible=()),),
    )
    with pytest.raises(InvalidInstanceError) as info:
        svc.save_instance(session, bad, name="bad")
    assert any("no eligible resources" in issue for issue in info.value.issues)

    with pytest.raises(ValueError, match="time_unit_minutes"):
        svc.save_instance(session, preset("tiny"), name="x", time_unit_minutes=0)


def test_unknown_ids(session: Session) -> None:
    with pytest.raises(ScenarioNotFoundError):
        svc.load_instance(session, 999_999)
    with pytest.raises(ScenarioNotFoundError):
        svc.delete_scenario(session, 999_999)
    with pytest.raises(RunNotFoundError):
        svc.load_run_assignments(session, 999_999)


def test_replace_instance_when_unlocked(session: Session) -> None:
    scenario = svc.save_instance(session, preset("tiny"), name="s")
    svc.replace_instance(session, scenario.id, preset("small"))
    session.expire_all()
    assert instance_hash(svc.load_instance(session, scenario.id)) == instance_hash(preset("small"))
    assert not svc.scenario_has_runs(session, scenario.id)


def test_clone_copies_inputs_only(session: Session) -> None:
    source = svc.save_instance(
        session, preset("tiny"), name="source", description="d", seed=9, time_unit_minutes=30
    )
    clone = svc.clone_scenario(session, source.id, name="copy")
    assert clone.id != source.id
    assert (clone.name, clone.description, clone.seed, clone.time_unit_minutes) == (
        "copy",
        "d",
        9,
        30,
    )
    assert instance_hash(svc.load_instance(session, clone.id)) == instance_hash(
        svc.load_instance(session, source.id)
    )


def test_delete_cascades_to_every_table(session: Session) -> None:
    scenario = svc.save_instance(session, preset("small"), name="s")
    svc.delete_scenario(session, scenario.id)
    for table in (
        orm.Scenario,
        orm.Resource,
        orm.ResourceWindow,
        orm.Job,
        orm.ScheduleRun,
        orm.Assignment,
        orm.RunMetrics,
        orm.job_eligible_resources,
    ):
        assert session.scalar(select(func.count()).select_from(table)) == 0


def test_locked_scenario_message(session: Session) -> None:
    assert "clone it" in str(ScenarioLockedError(1))


def test_work_jobs_and_line_capacity_round_trip(session: Session) -> None:
    problem = preset("opc")
    scenario = svc.save_instance(session, problem, name="opc")
    session.expire_all()
    assert svc.load_instance(session, scenario.id) == problem
