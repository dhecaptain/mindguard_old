"""Mark provisioned staff as non-consumer accounts."""

from typing import Sequence, Union

from alembic import op


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE users SET user_category = 'staff', "
        "onboarding_completed_at = COALESCE(onboarding_completed_at, created_at) "
        "WHERE role_type IN ('admin', 'school_admin', 'counsellor') "
        "AND (user_category IS NULL OR user_category = 'pending')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE users SET user_category = 'pending', onboarding_completed_at = NULL "
        "WHERE role_type IN ('admin', 'school_admin', 'counsellor') "
        "AND user_category = 'staff'"
    )
