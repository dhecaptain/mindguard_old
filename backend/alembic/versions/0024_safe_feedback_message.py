"""Separate student-safe feedback from private counsellor notes."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    try:
        op.add_column("notes", sa.Column("student_message", sa.Text(), nullable=True))
    except Exception:
        pass
    # Existing explicitly shared notes were already intended for the student;
    # preserve them in the new safe-message field during migration.
    op.execute(
        "UPDATE notes SET student_message = body "
        "WHERE visibility = 'student' AND student_message IS NULL"
    )


def downgrade() -> None:
    try:
        op.drop_column("notes", "student_message")
    except Exception:
        pass
