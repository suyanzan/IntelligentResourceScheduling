"""Initial schema.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
STATUSES = "'OPTIMAL', 'FEASIBLE', 'INFEASIBLE', 'UNKNOWN', 'MODEL_INVALID'"


def upgrade() -> None:
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("horizon_start", sa.Date(), nullable=True),
        sa.Column("horizon_units", sa.Integer(), nullable=False),
        sa.Column("time_unit_minutes", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("horizon_units > 0", name=op.f("ck_scenarios_horizon_positive")),
        sa.CheckConstraint(
            "time_unit_minutes BETWEEN 1 AND 1440", name=op.f("ck_scenarios_time_unit_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenarios")),
    )

    op.create_table(
        "resources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("daily_capacity_units", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "daily_capacity_units IS NULL OR daily_capacity_units >= 0",
            name=op.f("ck_resources_capacity_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
            name=op.f("fk_resources_scenario_id_scenarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resources")),
        sa.UniqueConstraint("scenario_id", "code", name="uq_resources_scenario_code"),
    )

    op.create_table(
        "resource_windows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("start_unit", sa.Integer(), nullable=False),
        sa.Column("end_unit", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "start_unit >= 0 AND start_unit < end_unit",
            name=op.f("ck_resource_windows_window_order"),
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            name=op.f("fk_resource_windows_resource_id_resources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_windows")),
    )
    op.create_index(
        op.f("ix_resource_windows_resource_id"), "resource_windows", ["resource_id"], unique=False
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("duration_units", sa.Integer(), nullable=False),
        sa.Column("due_unit", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("release_unit", sa.Integer(), nullable=False),
        sa.CheckConstraint("duration_units > 0", name=op.f("ck_jobs_duration_positive")),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name=op.f("ck_jobs_priority_range")),
        sa.CheckConstraint("release_unit >= 0", name=op.f("ck_jobs_release_nonnegative")),
        sa.CheckConstraint("due_unit >= 0", name=op.f("ck_jobs_due_nonnegative")),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
            name=op.f("fk_jobs_scenario_id_scenarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("scenario_id", "code", name="uq_jobs_scenario_code"),
    )

    op.create_table(
        "job_eligible_resources",
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_job_eligible_resources_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            name=op.f("fk_job_eligible_resources_resource_id_resources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id", "resource_id", name=op.f("pk_job_eligible_resources")),
    )

    op.create_table(
        "schedule_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("objective_value", sa.BigInteger(), nullable=True),
        sa.Column("best_bound", sa.Float(), nullable=True),
        sa.Column("gap", sa.Float(), nullable=True),
        sa.Column("wall_time_s", sa.Float(), nullable=False),
        sa.Column("time_limit_s", sa.Float(), nullable=False),
        sa.Column("num_workers", sa.Integer(), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("weighted", sa.Boolean(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("solver_version", sa.String(length=32), nullable=False),
        sa.Column("messages", JSON_TYPE, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f("ck_schedule_runs_status_valid")),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
            name=op.f("fk_schedule_runs_scenario_id_scenarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_runs")),
    )
    op.create_index(
        op.f("ix_schedule_runs_scenario_id"), "schedule_runs", ["scenario_id"], unique=False
    )

    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("start_unit", sa.Integer(), nullable=False),
        sa.Column("end_unit", sa.Integer(), nullable=False),
        sa.Column("tardiness_units", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "start_unit >= 0 AND start_unit < end_unit", name=op.f("ck_assignments_span_order")
        ),
        sa.CheckConstraint(
            "tardiness_units >= 0", name=op.f("ck_assignments_tardiness_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["schedule_runs.id"],
            name=op.f("fk_assignments_run_id_schedule_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_assignments_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            name=op.f("fk_assignments_resource_id_resources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assignments")),
        sa.UniqueConstraint("run_id", "job_id", name="uq_assignments_run_job"),
    )

    op.create_table(
        "run_metrics",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("on_time_rate", sa.Float(), nullable=False),
        sa.Column("total_tardiness", sa.BigInteger(), nullable=False),
        sa.Column("weighted_tardiness", sa.BigInteger(), nullable=False),
        sa.Column("makespan", sa.Integer(), nullable=False),
        sa.Column("utilization", JSON_TYPE, nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["schedule_runs.id"],
            name=op.f("fk_run_metrics_run_id_schedule_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_run_metrics")),
    )


def downgrade() -> None:
    op.drop_table("run_metrics")
    op.drop_table("assignments")
    op.drop_index(op.f("ix_schedule_runs_scenario_id"), table_name="schedule_runs")
    op.drop_table("schedule_runs")
    op.drop_table("job_eligible_resources")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_resource_windows_resource_id"), table_name="resource_windows")
    op.drop_table("resource_windows")
    op.drop_table("resources")
    op.drop_table("scenarios")
