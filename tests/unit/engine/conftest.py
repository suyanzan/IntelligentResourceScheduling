"""Hand-built fixtures for engine unit tests (no solver, fully fictional data)."""

import pytest

from scheduler.engine.models import Assignment, Job, ProblemInstance, Resource, Window


@pytest.fixture
def problem() -> ProblemInstance:
    return ProblemInstance(
        horizon=24,
        resources=(
            Resource("R1", "Line A", (Window(0, 8), Window(10, 18))),
            Resource("R2", "Line B", (Window(0, 24),)),
        ),
        jobs=(
            Job("J1", "Job 1", duration=4, due=4, eligible=("R1", "R2"), priority=2),
            Job("J2", "Job 2", duration=6, due=6, eligible=("R1",), priority=2),
            Job("J3", "Job 3", duration=5, due=6, eligible=("R2",), priority=3),
        ),
    )


@pytest.fixture
def valid_assignments() -> list[Assignment]:
    """A valid schedule: only J2 is late (ends at 16, due 6 -> tardiness 10)."""
    return [
        Assignment("J1", "R1", 0, 4),
        Assignment("J2", "R1", 10, 16),
        Assignment("J3", "R2", 0, 5),
    ]
