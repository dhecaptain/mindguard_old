"""Add provider credential and workplace case continuity lifecycle."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workplace_provider_credentials", sa.Column("professional_type", sa.Text(), nullable=True))
    op.add_column("workplace_provider_credentials", sa.Column("valid_from", sa.Text(), nullable=True))
    op.add_column("workplace_provider_credentials", sa.Column("expires_at", sa.Text(), nullable=True))
    op.add_column("workplace_provider_credentials", sa.Column("reason_encrypted", sa.Text(), nullable=True))

    op.create_table(
        "workplace_provider_operations",
        sa.Column("provider_id", sa.Text(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("access_status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("availability", sa.Text(), nullable=False, server_default="available"),
        sa.Column("reason_encrypted", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.Text(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changed_at", sa.Text(), nullable=False),
    )
    op.execute(
        "INSERT INTO workplace_provider_operations (provider_id,access_status,availability,changed_at) "
        "SELECT DISTINCT p.provider_id,'active','available',datetime('now') FROM workplace_providers p "
        "JOIN workplace_provider_credentials c ON c.provider_id=p.provider_id "
        "WHERE c.status='verified'"
    )

    op.create_table(
        "workplace_provider_credential_history",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("provider_id", sa.Text(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("professional_type_encrypted", sa.Text(), nullable=True),
        sa.Column("title_encrypted", sa.Text(), nullable=False),
        sa.Column("qualification_encrypted", sa.Text(), nullable=False),
        sa.Column("registration_encrypted", sa.Text(), nullable=False),
        sa.Column("verification_reference_encrypted", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.Text(), nullable=False),
        sa.Column("reviewed_by", sa.Text(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("reason_encrypted", sa.Text(), nullable=True),
    )
    op.create_index("idx_workplace_provider_credential_history", "workplace_provider_credential_history", ["provider_id", "submitted_at"])
    op.execute(
        "INSERT INTO workplace_provider_credential_history "
        "(id,provider_id,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,submitted_at,reviewed_by,reviewed_at) "
        "SELECT lower(hex(randomblob(16))),provider_id,title_encrypted,qualification_encrypted,registration_encrypted,verification_reference_encrypted,status,reviewed_at,reviewed_by,reviewed_at "
        "FROM workplace_provider_credentials"
    )

    op.add_column("workplace_support_cases", sa.Column("assignment_status", sa.Text(), nullable=False, server_default="assigned"))
    op.add_column("workplace_support_cases", sa.Column("assigned_at", sa.Text(), nullable=True))
    op.add_column("workplace_support_cases", sa.Column("closed_by", sa.Text(), nullable=True))
    op.add_column("workplace_support_cases", sa.Column("closed_at", sa.Text(), nullable=True))
    op.execute("UPDATE workplace_support_cases SET assigned_at=created_at WHERE assigned_at IS NULL")

    op.create_table(
        "workplace_case_assignment_history",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("workplace_support_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", sa.Text(), sa.ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_provider_id", sa.Text(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("new_provider_id", sa.Text(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("worker_consent_at", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_workplace_case_assignment_history", "workplace_case_assignment_history", ["case_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("idx_workplace_case_assignment_history", table_name="workplace_case_assignment_history")
    op.drop_table("workplace_case_assignment_history")
    op.drop_column("workplace_support_cases", "closed_at")
    op.drop_column("workplace_support_cases", "closed_by")
    op.drop_column("workplace_support_cases", "assigned_at")
    op.drop_column("workplace_support_cases", "assignment_status")
    op.drop_index("idx_workplace_provider_credential_history", table_name="workplace_provider_credential_history")
    op.drop_table("workplace_provider_credential_history")
    op.drop_table("workplace_provider_operations")
    op.drop_column("workplace_provider_credentials", "reason_encrypted")
    op.drop_column("workplace_provider_credentials", "expires_at")
    op.drop_column("workplace_provider_credentials", "valid_from")
    op.drop_column("workplace_provider_credentials", "professional_type")
