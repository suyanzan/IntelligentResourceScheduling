"""Capacity-hours jobs that merge resources, and the mean delay metric.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resources", sa.Column("capacity", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_check_constraint(op.f("ck_resources_capacity_min"), "resources", "capacity >= 1")

    op.add_column("jobs", sa.Column("work", sa.Integer(), nullable=True))
    op.drop_constraint(op.f("ck_jobs_duration_positive"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_duration_valid"),
        "jobs",
        "duration_units >= 0 AND (work IS NOT NULL OR duration_units > 0)",
    )
    op.create_check_constraint(op.f("ck_jobs_work_positive"), "jobs", "work IS NULL OR work > 0")

    op.drop_constraint("uq_assignments_run_job", "assignments", type_="unique")
    op.create_unique_constraint(
        "uq_assignments_run_job_resource", "assignments", ["run_id", "job_id", "resource_id"]
    )

    op.add_column(
        "run_metrics", sa.Column("mean_delay", sa.Float(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("run_metrics", "mean_delay")

    op.drop_constraint("uq_assignments_run_job_resource", "assignments", type_="unique")
    op.create_unique_constraint("uq_assignments_run_job", "assignments", ["run_id", "job_id"])

    op.drop_constraint(op.f("ck_jobs_work_positive"), "jobs", type_="check")
    op.drop_constraint(op.f("ck_jobs_duration_valid"), "jobs", type_="check")
    op.create_check_constraint(op.f("ck_jobs_duration_positive"), "jobs", "duration_units > 0")
    op.drop_column("jobs", "work")

    op.drop_constraint(op.f("ck_resources_capacity_min"), "resources", type_="check")
    op.drop_column("resources", "capacity")
