"""Add an organisation-neutral population field to demo requests."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("demo_requests", sa.Column("population_range", sa.Text(), nullable=True))
    op.execute(
        "UPDATE demo_requests SET population_range = CASE "
        "WHEN lower(organisation_type) = 'company' THEN "
        "COALESCE(NULLIF(employee_population_range, ''), student_count_range) "
        "ELSE COALESCE(NULLIF(student_count_range, ''), employee_population_range) END "
        "WHERE population_range IS NULL"
    )


def downgrade() -> None:
    op.drop_column("demo_requests", "population_range")
