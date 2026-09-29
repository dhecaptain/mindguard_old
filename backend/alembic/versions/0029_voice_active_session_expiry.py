"""Add an application-enforced active-session expiry for voice support."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "voice_support_sessions",
        sa.Column("active_expires_at", sa.Text(), nullable=True),
    )
    # Any session created before this migration is closed during the upgrade;
    # it must not gain a fresh active window after deployment.
    op.execute(
        "UPDATE voice_support_sessions "
        "SET status='expired', active_expires_at=created_at "
        "WHERE active_expires_at IS NULL AND status='active'"
    )
    op.execute(
        "UPDATE voice_support_sessions SET active_expires_at=created_at "
        "WHERE active_expires_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("voice_support_sessions", "active_expires_at")
