"""Link qualified demo leads to meetings and institution onboarding."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name, column in [
        ("meeting_at", sa.Column("meeting_at", sa.Text(), nullable=True)),
        ("meeting_url", sa.Column("meeting_url", sa.Text(), nullable=True)),
        ("institution_id", sa.Column("institution_id", sa.Text(), nullable=True)),
        ("converted_by", sa.Column("converted_by", sa.Text(), nullable=True)),
        ("converted_at", sa.Column("converted_at", sa.Text(), nullable=True)),
    ]:
        try:
            op.add_column("demo_requests", column)
        except Exception:
            pass
    try:
        op.create_index("idx_demo_requests_institution", "demo_requests", ["institution_id"])
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("idx_demo_requests_institution", table_name="demo_requests")
    except Exception:
        pass
    for name in ["converted_at", "converted_by", "institution_id", "meeting_url", "meeting_at"]:
        try:
            op.drop_column("demo_requests", name)
        except Exception:
            pass
