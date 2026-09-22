"""Institution onboarding lifecycle and staff profile fields."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name, typ in [
        ("phone", sa.Text()),
        ("country", sa.Text()),
        ("address", sa.Text()),
        ("professional_title", sa.Text()),
        ("qualification", sa.Text()),
        ("emergency_contact", sa.Text()),
        ("profile_completed_at", sa.Text()),
    ]:
        try:
            op.add_column("users", sa.Column(name, typ, nullable=True))
        except Exception:
            pass

    try:
        op.execute("UPDATE institutions SET status = 'PROVISIONING' WHERE status IS NULL OR status = ''")
    except Exception:
        pass


def downgrade() -> None:
    for name in [
        "profile_completed_at",
        "emergency_contact",
        "qualification",
        "professional_title",
        "address",
        "country",
        "phone",
    ]:
        try:
            op.drop_column("users", name)
        except Exception:
            pass
