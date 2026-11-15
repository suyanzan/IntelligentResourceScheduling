"""Successor jobs, cycle limits (DIFFUSION), merge cap and cycle points.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("scenarios", sa.Column("max_merge_capacity", sa.Integer(), nullable=True))
    op.add_column(
        "scenarios",
        sa.Column("cycle_penalty", sa.Integer(), nullable=False, server_default="50"),
    )
    op.add_column("jobs", sa.Column("after_code", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("cycle_limit", sa.Integer(), nullable=True))
    op.add_column(
        "jobs", sa.Column("layer", sa.String(length=64), nullable=False, server_default="")
    )
    op.add_column(
        "run_metrics",
        sa.Column("cycle_points", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("run_metrics", "cycle_points")
    op.drop_column("jobs", "layer")
    op.drop_column("jobs", "cycle_limit")
    op.drop_column("jobs", "after_code")
    op.drop_column("scenarios", "cycle_penalty")
    op.drop_column("scenarios", "max_merge_capacity")
