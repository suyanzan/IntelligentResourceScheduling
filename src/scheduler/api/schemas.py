"""Pydantic request and response schemas.

Field-level limits catch malformed requests (422 with field details). Cross-field rules such as
overlapping windows or unknown resources are enforced by the engine's validation, which the
service layer runs before storing anything (422 with a readable ``issues`` list).
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

# --- instance ----------------------------------------------------------------------------------


class WindowIn(BaseModel):
    start: int = Field(ge=0, description="First unit of the window (inclusive).")
    end: int = Field(gt=0, description="Unit after the last one (exclusive).")


class ResourceIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    windows: list[WindowIn] = Field(max_length=2000)
    capacity: int = Field(
        default=1, ge=1, description="Processing capacity per unit (e.g. CPUs), used by work jobs."
    )


class JobIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    duration: int = Field(default=0, ge=0, description="Fixed units; omit when ``work`` is given.")
    due: int = Field(ge=0)
    eligible: list[str]
    priority: int = Field(default=1, ge=1, le=5)
    release: int = Field(default=0, ge=0)
    work: int | None = Field(
        default=None,
        gt=0,
        description="Capacity-hours (e.g. CPU-hours). The job may then use several eligible "
        "resources at once; its duration is ceil(work / total capacity of those resources).",
    )
    after: str | None = Field(
        default=None, description="Id of a job that must end before this one starts."
    )
    cycle_limit: int | None = Field(
        default=None,
        gt=0,
        description="Units from release to end; going over it earns one cycle point.",
    )
    layer: str = Field(default="", max_length=64, description="Label such as DIFFUSION.")

    @model_validator(mode="after")
    def _duration_or_work(self) -> JobIn:
        if self.work is None and self.duration <= 0:
            raise ValueError("duration must be positive unless work is given")
        return self


class InstanceIn(BaseModel):
    horizon: int = Field(gt=0, le=100_000)
    resources: list[ResourceIn] = Field(min_length=1, max_length=100)
    jobs: list[JobIn] = Field(min_length=1, max_length=1000)
    max_merge_capacity: int | None = Field(
        default=None, ge=1, description="Largest total capacity of the lines one job may merge."
    )
    cycle_penalty: int = Field(default=50, ge=0, description="Objective cost of a cycle point.")


class ResourceOut(ResourceIn):
    daily_capacity_units: int | None


class InstanceOut(BaseModel):
    horizon: int
    resources: list[ResourceOut]
    jobs: list[JobIn]
    max_merge_capacity: int | None = None
    cycle_penalty: int = 50


# --- scenarios ---------------------------------------------------------------------------------


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    horizon_start: dt.date | None = None
    time_unit_minutes: int = Field(default=60, ge=1, le=1440)
    seed: int | None = Field(default=None, ge=0)
    instance: InstanceIn


class CloneRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class GenerateRequest(BaseModel):
    """Either a named ``preset`` or custom sizes (every custom field is optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    preset: Literal["tiny", "small", "medium", "opc", "opc_live"] | None = None
    seed: int | None = Field(default=None, ge=0)
    num_resources: int | None = Field(default=None, ge=1, le=20)
    num_jobs: int | None = Field(default=None, ge=1, le=200)
    num_days: int | None = Field(default=None, ge=3, le=60)

    @model_validator(mode="after")
    def _preset_excludes_custom_fields(self) -> GenerateRequest:
        custom = (self.seed, self.num_resources, self.num_jobs, self.num_days)
        if self.preset is not None and any(v is not None for v in custom):
            raise ValueError("give either a preset or custom sizes, not both")
        return self


class ScenarioSummary(BaseModel):
    id: int
    name: str
    description: str
    horizon_start: dt.date | None
    horizon_units: int
    time_unit_minutes: int
    seed: int | None
    created_at: dt.datetime
    resource_count: int
    job_count: int
    run_count: int


class ScenarioDetail(ScenarioSummary):
    instance: InstanceOut


# --- runs --------------------------------------------------------------------------------------


RunStatus = Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID"]


class SolveRequest(BaseModel):
    time_limit_s: float = Field(default=30.0, gt=0)
    num_workers: int = Field(default=1, ge=1, le=16)
    random_seed: int = Field(default=0, ge=0)
    weighted: bool = True
    no_idle: bool = Field(
        default=False,
        description="Keep every line busy while a job it can run has not started "
        "(needs release times of 0).",
    )


class MetricsOut(BaseModel):
    on_time_rate: float
    total_tardiness: int
    weighted_tardiness: int
    makespan: int
    utilization: dict[str, float]
    mean_delay: float = Field(
        description="Sum of positive delays divided by the number of jobs (early jobs count as 0)."
    )
    cycle_points: int = Field(
        default=0, description="Jobs that went over their cycle limit (one point each)."
    )


class AssignmentOut(BaseModel):
    job_id: str
    job_name: str
    resource_id: str
    resource_name: str
    start: int
    end: int
    due: int
    priority: int
    tardiness: int
    delay: int = Field(description="end - due in units; negative when the job is early.")
    work: int | None = None
    release: int = 0
    layer: str = ""
    cycle_limit: int | None = None
    over_cycle: bool = Field(default=False, description="True when the cycle limit was exceeded.")
    after: str | None = None
    start_at: dt.datetime | None = None
    end_at: dt.datetime | None = None


class RunSummary(BaseModel):
    id: int
    scenario_id: int
    status: RunStatus
    objective_value: int | None
    best_bound: float | None
    gap: float | None
    wall_time_s: float
    time_limit_s: float
    num_workers: int
    random_seed: int
    weighted: bool
    no_idle: bool
    input_hash: str
    solver_version: str
    messages: list[str]
    created_at: dt.datetime
    metrics: MetricsOut | None


class RunDetail(RunSummary):
    horizon_start: dt.date | None
    time_unit_minutes: int
    assignments: list[AssignmentOut]


# --- comparison --------------------------------------------------------------------------------


class DeltaOut(BaseModel):
    a: float | None
    b: float | None
    change: float | None = Field(description="b minus a; null when either run lacks the value.")


class PlacementOut(BaseModel):
    resource_id: str
    start: int
    end: int
    tardiness: int


class JobDiffOut(BaseModel):
    job_id: str
    job_name: str
    a: PlacementOut | None
    b: PlacementOut | None
    moved: bool
    tardiness_change: int | None


class ComparisonOut(BaseModel):
    a: RunSummary
    b: RunSummary
    same_scenario: bool
    same_inputs: bool
    objective_comparable: bool
    better: Literal["a", "b", "tie"] | None
    metrics: dict[str, DeltaOut]
    utilization: dict[str, DeltaOut]
    jobs: list[JobDiffOut]
    moved_jobs: int
    notes: list[str]


# --- production floor ------------------------------------------------------------------------


class ReleaseRequest(BaseModel):
    run_id: int
    released_by: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=2000)


class StartRequest(BaseModel):
    at: AwareDatetime | None = Field(default=None, description="Real start time; default now.")
    by: str = Field(default="", max_length=80)
    note: str | None = Field(default=None, max_length=2000)


class CompleteRequest(BaseModel):
    at: AwareDatetime | None = Field(default=None, description="Real finish time; default now.")
    started_at: AwareDatetime | None = Field(
        default=None, description="Real start time; required if the job was never started."
    )
    by: str = Field(default="", max_length=80)
    note: str | None = Field(default=None, max_length=2000)


class RevertRequest(BaseModel):
    by: str = Field(default="", max_length=80)


class NoteRequest(BaseModel):
    note: str = Field(max_length=2000)
    by: str = Field(default="", max_length=80)


class FloorLineOut(BaseModel):
    id: str
    name: str
    capacity: int


class FloorJobOut(BaseModel):
    id: str
    name: str
    layer: str
    priority: int
    work: int | None
    after: str | None
    cycle_limit_minutes: int | None
    due_at: dt.datetime
    planned_start_at: dt.datetime
    planned_end_at: dt.datetime
    lines: list[str]
    status: Literal["planned", "running", "done"]
    actual_start_at: dt.datetime | None
    actual_end_at: dt.datetime | None
    note: str
    updated_by: str
    updated_at: dt.datetime | None


class PlanOut(BaseModel):
    id: int
    active: bool
    scenario_id: int
    scenario_name: str
    run_id: int
    released_at: dt.datetime
    released_by: str
    note: str
    utc_offset_minutes: int
    time_unit_minutes: int
    server_time: dt.datetime
    lines: list[FloorLineOut]
    jobs: list[FloorJobOut]


class EventOut(BaseModel):
    id: int
    job_id: str
    job_name: str
    action: str
    actor: str
    recorded_at: dt.datetime
    effective_at: dt.datetime | None
    note: str
