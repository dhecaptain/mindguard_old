"""Add recipient-facing demo invitation and reschedule response state."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name, column in [
        ("meeting_response", sa.Column("meeting_response", sa.Text(), nullable=True)),
        ("meeting_response_token_hash", sa.Column("meeting_response_token_hash", sa.Text(), nullable=True)),
        ("meeting_response_note", sa.Column("meeting_response_note", sa.Text(), nullable=True)),
    ]:
        try:
            op.add_column("demo_requests", column)
        except Exception:
            pass
    try:
        op.create_index("idx_demo_requests_response_token", "demo_requests", ["meeting_response_token_hash"])
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("idx_demo_requests_response_token", table_name="demo_requests")
    except Exception:
        pass
    for name in ["meeting_response_note", "meeting_response_token_hash", "meeting_response"]:
        try:
            op.drop_column("demo_requests", name)
        except Exception:
            pass
