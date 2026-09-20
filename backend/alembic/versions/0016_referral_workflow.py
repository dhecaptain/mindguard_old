"""Extend referrals into an auditable institution care workflow."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name in ["destination", "follow_up_at", "outcome"]:
        try:
            op.add_column("referrals", sa.Column(name, sa.Text(), nullable=True))
        except Exception:
            pass
    try:
        op.create_table(
            "referral_events",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("referral_id", sa.Text(), sa.ForeignKey("referrals.id"), nullable=False),
            sa.Column("actor_id", sa.Text(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("actor_role", sa.Text(), nullable=True),
            sa.Column("from_status", sa.Text(), nullable=True),
            sa.Column("to_status", sa.Text(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
    except Exception:
        pass
    try:
        op.create_index("idx_referral_events_referral", "referral_events", ["referral_id", "created_at"])
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("idx_referral_events_referral", table_name="referral_events")
    except Exception:
        pass
    try:
        op.drop_table("referral_events")
    except Exception:
        pass
    for name in ["outcome", "follow_up_at", "destination"]:
        try:
            op.drop_column("referrals", name)
        except Exception:
            pass
