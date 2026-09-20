"""Add counsellor/student appointment scheduling.

Appointments are deliberately separate from referrals and communications so
that scheduling has an auditable lifecycle and cannot be inferred from either
table's free-form content.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("student_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("counsellor_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_by", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("start_at", sa.Text(), nullable=False),
        sa.Column("end_at", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="UTC"),
        sa.Column("mode", sa.Text(), nullable=False, server_default="video"),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="REQUESTED"),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_appointments_student", "appointments", ["student_id", "start_at"])
    op.create_index("idx_appointments_counsellor", "appointments", ["counsellor_id", "start_at"])
    op.create_index("idx_appointments_status", "appointments", ["status", "start_at"])


def downgrade() -> None:
    op.drop_index("idx_appointments_status", table_name="appointments")
    op.drop_index("idx_appointments_counsellor", table_name="appointments")
    op.drop_index("idx_appointments_student", table_name="appointments")
    op.drop_table("appointments")
