"""Domain errors raised by the service layer (the API layer maps these to HTTP responses)."""

from __future__ import annotations


class ScenarioNotFoundError(LookupError):
    def __init__(self, scenario_id: int) -> None:
        super().__init__(f"scenario {scenario_id} not found")
        self.scenario_id = scenario_id


class RunNotFoundError(LookupError):
    def __init__(self, run_id: int) -> None:
        super().__init__(f"run {run_id} not found")
        self.run_id = run_id


class ScenarioLockedError(RuntimeError):
    """Inputs cannot change once runs exist; clone the scenario and edit the clone."""

    def __init__(self, scenario_id: int) -> None:
        super().__init__(
            f"scenario {scenario_id} already has runs and its inputs are locked; "
            "clone it to make changes"
        )
        self.scenario_id = scenario_id


class PlanNotFoundError(LookupError):
    def __init__(self, message: str = "no plan has been released to the floor yet") -> None:
        super().__init__(message)


class PlanError(RuntimeError):
    """A run cannot be released, or a floor update does not fit the job's state."""


class InvalidInstanceError(ValueError):
    """The problem instance failed engine validation."""

    def __init__(self, issues: list[str]) -> None:
        super().__init__("invalid instance: " + "; ".join(issues))
        self.issues = issues
