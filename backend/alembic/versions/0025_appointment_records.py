"""Add structured post-appointment wellbeing records."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "appointment_records",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("appointment_id", sa.Text(), sa.ForeignKey("appointments.id"), nullable=False, unique=True),
        sa.Column("student_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("counsellor_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("private_summary", sa.Text(), nullable=False),
        sa.Column("student_message", sa.Text(), nullable=True),
        sa.Column("guardian_message", sa.Text(), nullable=True),
        sa.Column("referral_summary", sa.Text(), nullable=True),
        sa.Column("safeguarding_flag", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("follow_up_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_appointment_records_student", "appointment_records", ["student_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_appointment_records_student", table_name="appointment_records")
    op.drop_table("appointment_records")
