"""Add indexes for scoped messaging and live-change cursors."""

from typing import Sequence, Union

from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_communications_sender_created", "communications", ["sender_id", "created_at", "id"])
    op.create_index("idx_communications_receiver_created", "communications", ["receiver_id", "created_at", "id"])
    op.create_index("idx_group_members_user_group", "group_members", ["user_id", "group_id"])
    op.create_index("idx_group_messages_group_created", "group_messages", ["group_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("idx_group_messages_group_created", table_name="group_messages")
    op.drop_index("idx_group_members_user_group", table_name="group_members")
    op.drop_index("idx_communications_receiver_created", table_name="communications")
    op.drop_index("idx_communications_sender_created", table_name="communications")
