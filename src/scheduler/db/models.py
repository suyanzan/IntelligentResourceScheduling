"""SQLAlchemy models.

All input data is scoped to a scenario. A solve creates an immutable :class:`ScheduleRun`
(with its assignments and metrics); ``input_hash`` records exactly which inputs it was solved on.
Times are integer units counted from 0 (see :mod:`scheduler.engine.models`).

Deletes cascade in the database (``ON DELETE CASCADE``); relationships use ``passive_deletes``
so the ORM relies on that instead of loading children first.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scheduler.db.base import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")

RUN_STATUSES = ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN", "MODEL_INVALID")

job_eligible_resources = Table(
    "job_eligible_resources",
    Base.metadata,
    Column("job_id", ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
    Column("resource_id", ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True),
)


class Scenario(Base):
    __tablename__ = "scenarios"
    __table_args__ = (
        CheckConstraint("horizon_units > 0", name="horizon_positive"),
        CheckConstraint("time_unit_minutes BETWEEN 1 AND 1440", name="time_unit_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    horizon_start: Mapped[dt.date | None] = mapped_column(Date)
    horizon_units: Mapped[int]
    time_unit_minutes: Mapped[int] = mapped_column(default=60)
    seed: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    resources: Mapped[list[Resource]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Resource.id",
    )
    jobs: Mapped[list[Job]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Job.id",
    )
    runs: Mapped[list[ScheduleRun]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScheduleRun.id",
    )


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("scenario_id", "code", name="uq_resources_scenario_code"),
        CheckConstraint(
            "daily_capacity_units IS NULL OR daily_capacity_units >= 0", name="capacity_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    # Derived from the calendar: the most available units on any single day.
    daily_capacity_units: Mapped[int | None]

    scenario: Mapped[Scenario] = relationship(back_populates="resources")
    windows: Mapped[list[ResourceWindow]] = relationship(
        back_populates="resource",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ResourceWindow.start_unit",
    )


class ResourceWindow(Base):
    __tablename__ = "resource_windows"
    __table_args__ = (
        CheckConstraint("start_unit >= 0 AND start_unit < end_unit", name="window_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), index=True
    )
    start_unit: Mapped[int]
    end_unit: Mapped[int]

    resource: Mapped[Resource] = relationship(back_populates="windows")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("scenario_id", "code", name="uq_jobs_scenario_code"),
        CheckConstraint("duration_units > 0", name="duration_positive"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="priority_range"),
        CheckConstraint("release_unit >= 0", name="release_nonnegative"),
        CheckConstraint("due_unit >= 0", name="due_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    duration_units: Mapped[int]
    due_unit: Mapped[int]
    priority: Mapped[int]
    release_unit: Mapped[int] = mapped_column(default=0)

    scenario: Mapped[Scenario] = relationship(back_populates="jobs")
    eligible_resources: Mapped[list[Resource]] = relationship(secondary=job_eligible_resources)


class ScheduleRun(Base):
    __tablename__ = "schedule_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in RUN_STATUSES) + ")", name="status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16))
    objective_value: Mapped[int | None] = mapped_column(BigInteger)
    best_bound: Mapped[float | None] = mapped_column(Float)
    gap: Mapped[float | None] = mapped_column(Float)
    wall_time_s: Mapped[float] = mapped_column(Float)
    time_limit_s: Mapped[float] = mapped_column(Float)
    num_workers: Mapped[int]
    random_seed: Mapped[int]
    weighted: Mapped[bool] = mapped_column(Boolean)
    input_hash: Mapped[str] = mapped_column(String(64))
    solver_version: Mapped[str] = mapped_column(String(32))
    messages: Mapped[list[str]] = mapped_column(JsonType, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    scenario: Mapped[Scenario] = relationship(back_populates="runs")
    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Assignment.id",
    )
    metrics: Mapped[RunMetrics | None] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("run_id", "job_id", name="uq_assignments_run_job"),
        CheckConstraint("start_unit >= 0 AND start_unit < end_unit", name="span_order"),
        CheckConstraint("tardiness_units >= 0", name="tardiness_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("schedule_runs.id", ondelete="CASCADE"))
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"))
    start_unit: Mapped[int]
    end_unit: Mapped[int]
    tardiness_units: Mapped[int]

    run: Mapped[ScheduleRun] = relationship(back_populates="assignments")
    job: Mapped[Job] = relationship()
    resource: Mapped[Resource] = relationship()


class RunMetrics(Base):
    __tablename__ = "run_metrics"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="CASCADE"), primary_key=True
    )
    on_time_rate: Mapped[float] = mapped_column(Float)
    total_tardiness: Mapped[int] = mapped_column(BigInteger)
    weighted_tardiness: Mapped[int] = mapped_column(BigInteger)
    makespan: Mapped[int]
    utilization: Mapped[dict[str, float]] = mapped_column(JsonType)

    run: Mapped[ScheduleRun] = relationship(back_populates="metrics")
