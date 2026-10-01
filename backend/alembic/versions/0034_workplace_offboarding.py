"""Add explicit workplace offboarding and continuity metadata."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Company lifecycle is intentionally soft-state only. The RESTRICT FK here
    # also prevents deleting a company while its commercial history exists.
    op.create_table(
        "workplace_offboarding",
        sa.Column("company_id", sa.Text(), sa.ForeignKey("institutions.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="NOT_STARTED"),
        sa.Column("effective_date", sa.Text(), nullable=True),
        sa.Column("initiated_by", sa.Text(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("initiated_at", sa.Text(), nullable=True),
        sa.Column("reason_encrypted", sa.Text(), nullable=True),
        sa.Column("reference_encrypted", sa.Text(), nullable=True),
        sa.Column("continuity_deadline", sa.Text(), nullable=True),
        sa.Column("retention_deadline", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.add_column("workplace_memberships", sa.Column("ended_at", sa.Text(), nullable=True))
    op.add_column("workplace_memberships", sa.Column("end_reason", sa.Text(), nullable=True))
    op.add_column("workplace_support_cases", sa.Column("continuity_until", sa.Text(), nullable=True))
    op.add_column("workplace_providers", sa.Column("ended_at", sa.Text(), nullable=True))
    op.create_index("idx_workplace_offboarding_status", "workplace_offboarding", ["status", "effective_date"])


def downgrade() -> None:
    op.drop_index("idx_workplace_offboarding_status", table_name="workplace_offboarding")
    op.drop_column("workplace_providers", "ended_at")
    op.drop_column("workplace_support_cases", "continuity_until")
    op.drop_column("workplace_memberships", "end_reason")
    op.drop_column("workplace_memberships", "ended_at")
    op.drop_table("workplace_offboarding")
