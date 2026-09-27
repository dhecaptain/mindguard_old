"""Add privacy-bounded workplace wellbeing pilot entities."""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "demo_requests",
        sa.Column("employee_population_range", sa.Text(), nullable=True),
    )
    op.create_table(
        "workplace_settings",
        sa.Column(
            "company_id",
            sa.Text(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("work_email_domains_json", sa.Text(), nullable=False),
        sa.Column(
            "privacy_notice_version",
            sa.Text(),
            nullable=False,
            server_default="workplace-v1",
        ),
        sa.Column(
            "provider_service_enabled", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "legal_review_complete", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("legal_review_reference", sa.Text(), nullable=True),
        sa.Column(
            "legal_reviewed_by", sa.Text(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("legal_reviewed_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "workplace_enrollment_links",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Text(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "workplace_enrollment_challenges",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Text(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "link_id",
            sa.Text(),
            sa.ForeignKey("workplace_enrollment_links.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email_hash", sa.Text(), nullable=False),
        sa.Column("email_encrypted", sa.Text(), nullable=False),
        sa.Column("name_encrypted", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("attempts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("used_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "workplace_memberships",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Text(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("notice_version", sa.Text(), nullable=False),
        sa.Column("consented_at", sa.Text(), nullable=False),
        sa.Column("withdrawn_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "company_id", "user_id", name="uq_workplace_membership_company_user"
        ),
    )
    op.create_table(
        "workplace_providers",
        sa.Column(
            "company_id",
            sa.Text(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "provider_id", sa.Text(), sa.ForeignKey("users.id"), primary_key=True
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "workplace_provider_credentials",
        sa.Column(
            "provider_id",
            sa.Text(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("title_encrypted", sa.Text(), nullable=False),
        sa.Column("qualification_encrypted", sa.Text(), nullable=False),
        sa.Column("registration_encrypted", sa.Text(), nullable=False),
        sa.Column("verification_reference_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="verified"),
        sa.Column("reviewed_by", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "workplace_checkins",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Text(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("answers_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "workplace_support_cases",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Text(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("share_consent_at", sa.Text(), nullable=False),
        sa.Column(
            "shared_checkin_id",
            sa.Text(),
            sa.ForeignKey("workplace_checkins.id"),
            nullable=False,
        ),
        sa.Column("withdrawn_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "workplace_audit_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Text(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_workplace_memberships_company_status",
        "workplace_memberships",
        ["company_id", "status"],
    )
    op.create_index(
        "idx_workplace_checkins_company_created",
        "workplace_checkins",
        ["company_id", "created_at"],
    )
    op.create_index(
        "idx_workplace_checkins_user_created",
        "workplace_checkins",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_workplace_cases_provider_status",
        "workplace_support_cases",
        ["provider_id", "status"],
    )
    op.create_index(
        "idx_workplace_audit_company_time",
        "workplace_audit_events",
        ["company_id", "occurred_at"],
    )


def downgrade() -> None:
    for index, table in [
        ("idx_workplace_cases_provider_status", "workplace_support_cases"),
        ("idx_workplace_audit_company_time", "workplace_audit_events"),
        ("idx_workplace_checkins_user_created", "workplace_checkins"),
        ("idx_workplace_checkins_company_created", "workplace_checkins"),
        ("idx_workplace_memberships_company_status", "workplace_memberships"),
    ]:
        op.drop_index(index, table_name=table)
    for table in [
        "workplace_audit_events",
        "workplace_support_cases",
        "workplace_checkins",
        "workplace_provider_credentials",
        "workplace_providers",
        "workplace_memberships",
        "workplace_enrollment_challenges",
        "workplace_enrollment_links",
        "workplace_settings",
    ]:
        op.drop_table(table)
    op.drop_column("demo_requests", "employee_population_range")
