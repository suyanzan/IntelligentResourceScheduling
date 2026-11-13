"""The database itself rejects invalid rows (defence in depth behind engine validation)."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scheduler.db import models as orm


def _scenario(session: Session) -> orm.Scenario:
    scenario = orm.Scenario(name="s", horizon_units=24, time_unit_minutes=60)
    session.add(scenario)
    session.flush()
    return scenario


def _job(scenario_id: int, **overrides: object) -> orm.Job:
    fields: dict[str, object] = {
        "scenario_id": scenario_id,
        "code": "J1",
        "name": "job",
        "duration_units": 2,
        "due_unit": 5,
        "priority": 3,
        "release_unit": 0,
    }
    fields.update(overrides)
    return orm.Job(**fields)


def test_valid_rows_are_accepted(session: Session) -> None:
    scenario = _scenario(session)
    session.add(_job(scenario.id))
    session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"duration_units": 0},
        {"priority": 6},
        {"priority": 0},
        {"release_unit": -1},
        {"due_unit": -1},
    ],
)
def test_invalid_job_values_are_rejected(session: Session, overrides: dict[str, object]) -> None:
    scenario = _scenario(session)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(_job(scenario.id, **overrides))
        session.flush()


def test_duplicate_job_code_in_a_scenario_is_rejected(session: Session) -> None:
    scenario = _scenario(session)
    session.add(_job(scenario.id))
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(_job(scenario.id))
        session.flush()


def test_same_job_code_in_different_scenarios_is_allowed(session: Session) -> None:
    first, second = _scenario(session), _scenario(session)
    session.add_all([_job(first.id), _job(second.id)])
    session.flush()


@pytest.mark.parametrize("start,end", [(5, 5), (8, 4), (-1, 4)])
def test_invalid_windows_are_rejected(session: Session, start: int, end: int) -> None:
    scenario = _scenario(session)
    resource = orm.Resource(scenario_id=scenario.id, code="R1", name="a")
    session.add(resource)
    session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(orm.ResourceWindow(resource_id=resource.id, start_unit=start, end_unit=end))
        session.flush()


def test_invalid_scenario_values_are_rejected(session: Session) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(orm.Scenario(name="s", horizon_units=0, time_unit_minutes=60))
        session.flush()
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(orm.Scenario(name="s", horizon_units=10, time_unit_minutes=0))
        session.flush()


def test_unknown_run_status_is_rejected(session: Session) -> None:
    scenario = _scenario(session)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.add(
            orm.ScheduleRun(
                scenario_id=scenario.id,
                status="BOGUS",
                wall_time_s=0.0,
                time_limit_s=1.0,
                num_workers=1,
                random_seed=0,
                weighted=True,
                input_hash="0" * 64,
                solver_version="x",
                messages=[],
            )
        )
        session.flush()
