"""Counsellor-controlled, student-safe feedback visibility."""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column in [
        sa.Column("visibility", sa.Text(), nullable=True),
        sa.Column("student_title", sa.Text(), nullable=True),
        sa.Column("shared_at", sa.Text(), nullable=True),
    ]:
        try:
            op.add_column("notes", column)
        except Exception:
            pass
    op.execute(
        "UPDATE notes SET visibility = 'private' WHERE visibility IS NULL OR visibility = ''"
    )


def downgrade() -> None:
    for name in ["shared_at", "student_title", "visibility"]:
        try:
            op.drop_column("notes", name)
        except Exception:
            pass
