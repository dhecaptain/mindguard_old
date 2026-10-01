"""Harden workplace admin, invitation, terms, and existing-account enrollment."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("workplace_admin_role", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("workplace_invitation_status", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("workplace_terms_version", sa.Text(), nullable=True))

    # Preserve existing companies: make the earliest active administrator the
    # owner; if none is active, deterministically assign the earliest account.
    op.execute(
        "UPDATE users SET workplace_admin_role='owner' WHERE id IN ("
        "SELECT u.id FROM users u WHERE u.role_type='company_admin' AND u.institution_id IS NOT NULL "
        "AND u.id=(SELECT u2.id FROM users u2 WHERE u2.role_type='company_admin' "
        "AND u2.institution_id=u.institution_id ORDER BY "
        "CASE WHEN lower(u2.status) IN ('approved','active') THEN 0 ELSE 1 END, "
        "u2.created_at,u2.id LIMIT 1))"
    )
    op.execute(
        "UPDATE users SET workplace_admin_role='admin' WHERE role_type='company_admin' "
        "AND workplace_admin_role IS NULL"
    )
    op.execute(
        "UPDATE users SET workplace_invitation_status=CASE "
        "WHEN status='revoked' THEN 'revoked' "
        "WHEN lower(status) IN ('approved','active') THEN 'accepted' "
        "WHEN invitation_token_hash IS NOT NULL AND invitation_expires_at IS NOT NULL "
        "AND invitation_expires_at<=datetime('now') THEN 'expired' "
        "WHEN invitation_token_hash IS NOT NULL THEN 'pending' ELSE NULL END "
        "WHERE role_type='company_admin'"
    )
    op.create_index(
        "uq_workplace_company_owner",
        "users",
        ["institution_id"],
        unique=True,
        sqlite_where=sa.text("role_type='company_admin' AND workplace_admin_role='owner'"),
        postgresql_where=sa.text("role_type='company_admin' AND workplace_admin_role='owner'"),
    )

    op.create_table(
        "workplace_existing_enrollment_challenges",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("company_id", sa.Text(), sa.ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_id", sa.Text(), sa.ForeignKey("workplace_enrollment_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("attempts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notice_version", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("used_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_workplace_existing_enrollment_user",
        "workplace_existing_enrollment_challenges",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_workplace_existing_enrollment_user", table_name="workplace_existing_enrollment_challenges")
    op.drop_table("workplace_existing_enrollment_challenges")
    op.drop_index("uq_workplace_company_owner", table_name="users")
    op.drop_column("users", "workplace_terms_version")
    op.drop_column("users", "workplace_invitation_status")
    op.drop_column("users", "workplace_admin_role")
