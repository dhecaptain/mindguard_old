"""Track account identity, availability and re-verification state."""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column in [
        sa.Column("platform_account_id", sa.Text(), nullable=True),
        sa.Column("availability_status", sa.Text(), nullable=True),
        sa.Column("reverification_required", sa.Integer(), nullable=False, server_default="0"),
    ]:
        try:
            op.add_column("student_social_accounts", column)
        except Exception:
            pass
    op.execute("UPDATE student_social_accounts SET availability_status = 'available' WHERE availability_status IS NULL")
    op.execute("UPDATE student_social_accounts SET reverification_required = 1 WHERE verification_status IN ('legacy_unverified', 'failed')")


def downgrade() -> None:
    for name in ["reverification_required", "availability_status", "platform_account_id"]:
        try:
            op.drop_column("student_social_accounts", name)
        except Exception:
            pass
