"""Track server-authorized conversational Voice actions."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("voice_support_sessions") as batch:
        batch.add_column(sa.Column("pending_action_source", sa.Text(), nullable=True))
        batch.add_column(sa.Column("pending_action_confirmation_prompt", sa.Text(), nullable=True))
        batch.add_column(sa.Column("pending_action_prompted_at", sa.Text(), nullable=True))
        batch.add_column(sa.Column("navigation_event_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("navigation_route_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("navigation_created_at", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("voice_support_sessions") as batch:
        for column in (
            "navigation_created_at",
            "navigation_route_id",
            "navigation_event_id",
            "pending_action_prompted_at",
            "pending_action_confirmation_prompt",
            "pending_action_source",
        ):
            batch.drop_column(column)
