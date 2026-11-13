"""Solving a stored scenario and persisting the run. Needs OR-Tools as well as PostgreSQL."""

import pytest

pytest.importorskip("ortools")

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scheduler.db import models as orm  # noqa: E402
from scheduler.engine.metrics import compute_metrics, objective_value, verify_schedule  # noqa: E402
from scheduler.engine.models import SolveParams, SolveStatus  # noqa: E402
from scheduler.engine.serialization import instance_hash  # noqa: E402
from scheduler.services import scheduling_service as svc  # noqa: E402
from scheduler.services.errors import ScenarioLockedError  # noqa: E402
from scheduler.synthetic.generator import preset  # noqa: E402


def test_solve_persists_a_verified_run(session: Session) -> None:
    problem = preset("tiny")
    scenario = svc.save_instance(session, problem, name="s")
    run = svc.solve_scenario(session, scenario.id, SolveParams(time_limit_s=20.0))
    session.expire_all()

    assert run.status == "OPTIMAL"
    assert run.input_hash == instance_hash(problem)
    assert run.solver_version
    assert run.num_workers == 1 and run.weighted is True
    assert run.gap == 0

    stored = svc.load_run_assignments(session, run.id)
    assert len(stored) == len(problem.jobs)
    assert verify_schedule(problem, stored) == []
    assert run.objective_value == objective_value(problem, stored)

    metrics = compute_metrics(problem, stored)
    assert run.metrics is not None
    assert run.metrics.total_tardiness == metrics.total_tardiness
    assert run.metrics.weighted_tardiness == metrics.weighted_tardiness
    assert run.metrics.makespan == metrics.makespan
    assert run.metrics.on_time_rate == pytest.approx(metrics.on_time_rate)
    assert run.metrics.utilization == pytest.approx(metrics.utilization)
    assert sum(a.tardiness_units for a in run.assignments) == metrics.total_tardiness


def test_model_invalid_run_is_recorded_without_a_schedule(session: Session) -> None:
    scenario = svc.save_instance(session, preset("tiny"), name="s")
    run = svc.solve_scenario(session, scenario.id, SolveParams(time_limit_s=0.0))
    assert run.status == SolveStatus.MODEL_INVALID.value
    assert run.objective_value is None
    assert any("time_limit_s" in m for m in run.messages)
    assert run.assignments == []
    assert run.metrics is None


def test_runs_lock_the_inputs_but_a_clone_can_change(session: Session) -> None:
    scenario = svc.save_instance(session, preset("tiny"), name="s")
    svc.solve_scenario(session, scenario.id, SolveParams(time_limit_s=20.0))
    assert svc.scenario_has_runs(session, scenario.id)

    with pytest.raises(ScenarioLockedError):
        svc.replace_instance(session, scenario.id, preset("small"))

    clone = svc.clone_scenario(session, scenario.id, name="copy")
    assert not svc.scenario_has_runs(session, clone.id)
    svc.replace_instance(session, clone.id, preset("small"))


def test_deleting_a_scenario_removes_its_runs(session: Session) -> None:
    scenario = svc.save_instance(session, preset("tiny"), name="s")
    svc.solve_scenario(session, scenario.id, SolveParams(time_limit_s=20.0))
    svc.delete_scenario(session, scenario.id)
    for table in (orm.ScheduleRun, orm.Assignment, orm.RunMetrics):
        assert session.scalar(select(func.count()).select_from(table)) == 0
