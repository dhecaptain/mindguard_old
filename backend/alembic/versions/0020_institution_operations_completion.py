"""Institution operations completion: caseloads and revised consent reminders."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    try:
        op.add_column("users", sa.Column("max_caseload", sa.Integer(), nullable=True))
    except Exception:
        pass
    # Existing institutions inherit the agreed default. Explicitly configured
    # institutions retain their values.
    op.execute("UPDATE institutions SET consent_reminder_days = '[7,14]' WHERE consent_reminder_days IS NULL OR consent_reminder_days = '' OR consent_reminder_days = '[3,7]'")


def downgrade() -> None:
    try:
        op.drop_column("users", "max_caseload")
    except Exception:
        pass
