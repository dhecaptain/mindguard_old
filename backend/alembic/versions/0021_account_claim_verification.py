"""Account-claim verification required before counsellor analysis."""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name, column in [
        (
            "verification_method",
            sa.Column("verification_method", sa.Text(), nullable=True),
        ),
        (
            "verification_code_hash",
            sa.Column("verification_code_hash", sa.Text(), nullable=True),
        ),
        (
            "verification_required_at",
            sa.Column("verification_required_at", sa.Text(), nullable=True),
        ),
        ("previous_handle", sa.Column("previous_handle", sa.Text(), nullable=True)),
    ]:
        try:
            op.add_column("student_social_accounts", column)
        except Exception:
            pass
    # A historic connection did not prove account ownership.  It is safe to
    # keep the record, but unsafe to analyse it until the owner reclaims it.
    op.execute(
        "UPDATE student_social_accounts SET verification_status = 'legacy_unverified', analysis_status = 'blocked' WHERE active = 1"
    )


def downgrade() -> None:
    for name in [
        "previous_handle",
        "verification_required_at",
        "verification_code_hash",
        "verification_method",
    ]:
        try:
            op.drop_column("student_social_accounts", name)
        except Exception:
            pass
