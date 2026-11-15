import pytest

from scheduler.engine.comparison import METRIC_KEYS, Placement, RunView, compare
from scheduler.engine.models import Metrics


def metrics(*, total: int = 0, weighted: int = 0, makespan: int = 10, rate: float = 1.0,
            util: dict[str, float] | None = None) -> Metrics:
    return Metrics(
        job_count=3,
        on_time_count=3,
        on_time_rate=rate,
        total_tardiness=total,
        weighted_tardiness=weighted,
        makespan=makespan,
        utilization=util if util is not None else {"R1": 0.5},
    )


def view(run_id: int = 1, *, status: str = "OPTIMAL", objective: int | None = 0,
         input_hash: str = "h", weighted: bool = True, scenario_id: int = 1,
         m: Metrics | None = None, placements: dict[str, Placement] | None = None) -> RunView:
    return RunView(
        run_id=run_id,
        scenario_id=scenario_id,
        status=status,
        weighted=weighted,
        objective=objective,
        input_hash=input_hash,
        metrics=m,
        placements=placements or {},
        job_names={"J1": "Order 1", "J2": "Order 2", "J3": "Order 3"},
    )


def test_lower_objective_wins_and_changes_are_b_minus_a() -> None:
    a = view(1, objective=20, m=metrics(total=10, weighted=20, makespan=30, rate=0.6))
    b = view(2, objective=8, m=metrics(total=4, weighted=8, makespan=25, rate=0.8))
    result = compare(a, b)
    assert result.objective_comparable and result.better == "b"
    assert result.metrics["objective"].change == -12
    assert result.metrics["total_tardiness"].change == -6
    assert result.metrics["makespan"].change == -5
    assert result.metrics["on_time_rate"].change == pytest.approx(0.2)
    assert set(result.metrics) == set(METRIC_KEYS)
    assert result.same_scenario and result.same_inputs


def test_a_wins_and_tie() -> None:
    assert compare(view(objective=3, m=metrics()), view(objective=9, m=metrics())).better == "a"
    assert compare(view(objective=5, m=metrics()), view(objective=5, m=metrics())).better == "tie"


def test_different_inputs_are_not_ranked() -> None:
    a = view(objective=1, input_hash="x", m=metrics())
    b = view(objective=9, input_hash="y", m=metrics())
    result = compare(a, b)
    assert not result.same_inputs and not result.objective_comparable
    assert result.better is None
    assert result.metrics["objective"].change == 8  # still reported
    assert any("different inputs" in n for n in result.notes)


def test_different_objective_kinds_are_not_ranked() -> None:
    result = compare(view(weighted=True, m=metrics()), view(weighted=False, m=metrics()))
    assert result.better is None
    assert any("different objectives" in n for n in result.notes)


def test_run_without_schedule() -> None:
    a = view(1, status="UNKNOWN", objective=None, m=None)
    b = view(2, m=metrics(total=2))
    result = compare(a, b)
    assert result.better is None and not result.objective_comparable
    assert result.metrics["total_tardiness"].a is None
    assert result.metrics["total_tardiness"].change is None
    assert result.utilization["R1"].a is None and result.utilization["R1"].b == 0.5
    assert any("Run A has no schedule (UNKNOWN)" in n for n in result.notes)


def test_not_proven_optimal_is_noted() -> None:
    result = compare(view(status="FEASIBLE", m=metrics()), view(m=metrics()))
    assert any("Run A is not proven optimal (FEASIBLE)" in n for n in result.notes)
    assert not any("Run B" in n for n in result.notes)


def test_utilization_covers_every_line_of_either_run() -> None:
    a = view(m=metrics(util={"R1": 0.4, "R2": 0.9}))
    b = view(m=metrics(util={"R1": 0.6, "R3": 0.1}))
    util = compare(a, b).utilization
    assert list(util) == ["R1", "R2", "R3"]
    assert util["R1"].change == pytest.approx(0.2)
    assert util["R2"].b is None and util["R3"].a is None


def test_job_diff() -> None:
    a = view(m=metrics(), placements={
        "J1": Placement("R1", 0, 4, 0),
        "J2": Placement("R1", 4, 8, 2),
        "J3": Placement("R2", 0, 3, 0),
    })
    b = view(m=metrics(), placements={
        "J1": Placement("R1", 0, 4, 0),    # unchanged
        "J2": Placement("R2", 1, 5, 0),    # moved to another line, 2 less late
        "J4": Placement("R1", 8, 9, 1),    # only in b
    })
    result = compare(a, b)
    by_id = {d.job_id: d for d in result.jobs}
    assert list(by_id) == ["J1", "J2", "J3", "J4"]
    assert not by_id["J1"].moved and by_id["J1"].tardiness_change == 0
    assert by_id["J2"].moved and by_id["J2"].tardiness_change == -2
    assert by_id["J3"].b is None and not by_id["J3"].moved and by_id["J3"].tardiness_change is None
    assert by_id["J4"].a is None and not by_id["J4"].moved
    assert by_id["J2"].job_name == "Order 2"
    assert by_id["J4"].job_name == "J4"  # no name known for jobs outside the name map
    assert result.moved_jobs == 1


def test_same_start_on_same_line_is_not_a_move() -> None:
    p = {"J1": Placement("R1", 5, 9, 0)}
    result = compare(view(m=metrics(), placements=p), view(m=metrics(), placements=dict(p)))
    assert result.moved_jobs == 0


def test_different_scenarios_are_flagged() -> None:
    result = compare(view(scenario_id=1, m=metrics()), view(scenario_id=2, m=metrics()))
    assert not result.same_scenario
