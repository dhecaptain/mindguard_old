"""Add short-lived confirmation state for authorized Voice actions."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    with op.batch_alter_table("workplace_checkins") as batch:
        batch.add_column(sa.Column("origin", sa.Text(), nullable=False, server_default="web"))

    with op.batch_alter_table("voice_support_sessions") as batch:
        batch.add_column(sa.Column("pending_action_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("pending_action_type", sa.Text(), nullable=True))
        batch.add_column(sa.Column("pending_action_payload_encrypted", sa.Text(), nullable=True))
        batch.add_column(sa.Column("pending_action_expires_at", sa.Text(), nullable=True))
        batch.add_column(sa.Column("pending_action_state", sa.Text(), nullable=True))
        batch.add_column(sa.Column("summary_saved_at", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("voice_support_sessions") as batch:
        for column in (
            "summary_saved_at",
            "pending_action_state",
            "pending_action_expires_at",
            "pending_action_payload_encrypted",
            "pending_action_type",
            "pending_action_id",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("workplace_checkins") as batch:
        batch.drop_column("origin")
