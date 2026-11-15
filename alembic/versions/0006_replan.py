"""Re-planning from actual progress: scenario source plan and carried-over job placement.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("scenarios", sa.Column("source_plan_id", sa.Integer(), nullable=True))
    op.add_column("job_actuals", sa.Column("carried_start_unit", sa.Integer(), nullable=True))
    op.add_column("job_actuals", sa.Column("carried_end_unit", sa.Integer(), nullable=True))
    op.add_column("job_actuals", sa.Column("carried_due_unit", sa.Integer(), nullable=True))
    op.add_column(
        "job_actuals", sa.Column("carried_lines", sa.String(length=120), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("job_actuals", "carried_lines")
    op.drop_column("job_actuals", "carried_due_unit")
    op.drop_column("job_actuals", "carried_end_unit")
    op.drop_column("job_actuals", "carried_start_unit")
    op.drop_column("scenarios", "source_plan_id")
