"""Institution lifecycle, policy metadata, and explicit roster identity links."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column(table: str, column: sa.Column) -> None:
    try:
        op.add_column(table, column)
    except Exception:
        # Existing installations may already have one of these compatibility
        # columns from an unreleased schema build.
        pass


def upgrade() -> None:
    _add_column("institutions", sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"))
    _add_column("institutions", sa.Column("created_by", sa.Text(), sa.ForeignKey("users.id"), nullable=True))
    _add_column("institutions", sa.Column("updated_at", sa.Text(), nullable=True))
    _add_column("institutions", sa.Column("settings_version", sa.Integer(), nullable=False, server_default="1"))
    try:
        op.execute("UPDATE institutions SET status = 'ACTIVE' WHERE status IS NULL OR status = ''")
        op.execute("UPDATE institutions SET updated_at = created_at WHERE updated_at IS NULL")
    except Exception:
        pass
    try:
        op.create_index("idx_institutions_status", "institutions", ["status"])
    except Exception:
        pass

    _add_column("students", sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=True))
    _add_column("students", sa.Column("archived_at", sa.Text(), nullable=True))
    try:
        op.create_index("idx_students_user", "students", ["user_id"])
    except Exception:
        pass
    try:
        op.create_index("idx_students_institution_active", "students", ["institution_id", "deleted_at"])
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("idx_students_institution_active", table_name="students")
    except Exception:
        pass
    try:
        op.drop_index("idx_students_user", table_name="students")
    except Exception:
        pass
    for col in ["archived_at", "user_id"]:
        try:
            op.drop_column("students", col)
        except Exception:
            pass
    try:
        op.drop_index("idx_institutions_status", table_name="institutions")
    except Exception:
        pass
    for col in ["settings_version", "updated_at", "created_by", "status"]:
        try:
            op.drop_column("institutions", col)
        except Exception:
            pass
