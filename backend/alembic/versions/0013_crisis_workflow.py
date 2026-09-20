"""Add auditable crisis-alert workflow timestamps and escalation metadata."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name in ["acknowledged_by", "acknowledged_at", "escalated_at", "in_progress_at", "closed_reason"]:
        try:
            op.add_column("alerts", sa.Column(name, sa.Text(), nullable=True))
        except Exception:
            pass
    try:
        op.create_index("idx_alerts_status_fired", "alerts", ["status", "fired_at"])
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("idx_alerts_status_fired", table_name="alerts")
    except Exception:
        pass
    for name in ["closed_reason", "in_progress_at", "escalated_at", "acknowledged_at", "acknowledged_by"]:
        try:
            op.drop_column("alerts", name)
        except Exception:
            pass
