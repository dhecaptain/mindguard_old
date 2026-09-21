"""Store rate-limit windows in SQLite so limits are shared by workers."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.Float(), nullable=False),
    )
    op.create_index(
        "idx_rate_limit_events_bucket_time",
        "rate_limit_events",
        ["bucket", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_rate_limit_events_bucket_time", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
