"""Generated presets must be solvable and every returned schedule must verify.

Skipped automatically when OR-Tools is not installed; CI installs it and runs them.
"""

import pytest

pytest.importorskip("ortools")

from scheduler.engine.metrics import compute_metrics, objective_value, verify_schedule  # noqa: E402
from scheduler.engine.models import SolveParams, SolveStatus  # noqa: E402
from scheduler.engine.solver import solve  # noqa: E402
from scheduler.synthetic.generator import preset  # noqa: E402


def test_tiny_preset_solves_to_proven_optimum() -> None:
    problem = preset("tiny")
    result = solve(problem, SolveParams(time_limit_s=20.0))
    assert result.status is SolveStatus.OPTIMAL
    assert verify_schedule(problem, result.assignments) == []
    assert result.objective == objective_value(problem, result.assignments)
    assert len(result.assignments) == len(problem.jobs)


@pytest.mark.parametrize("name", ["small", "medium"])
def test_larger_presets_yield_verified_schedules(name: str) -> None:
    problem = preset(name)
    result = solve(problem, SolveParams(time_limit_s=10.0))
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
    assert verify_schedule(problem, result.assignments) == []
    assert result.objective == objective_value(problem, result.assignments)

    metrics = compute_metrics(problem, result.assignments)
    assert 0.0 <= metrics.on_time_rate <= 1.0
    assert all(0.0 <= u <= 1.0 for u in metrics.utilization.values())
