"""Complete workplace operations and add guest/voice support records."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workplace_settings") as batch:
        batch.add_column(sa.Column("privacy_contact_encrypted", sa.Text(), nullable=True))
        batch.add_column(sa.Column("employee_population_range", sa.Text(), nullable=True))
        batch.add_column(sa.Column("retention_days", sa.Integer(), nullable=False, server_default="365"))
        batch.add_column(sa.Column("policy_status", sa.Text(), nullable=False, server_default="draft"))
        batch.add_column(sa.Column("archived_at", sa.Text(), nullable=True))

    op.create_table(
        "workplace_case_notes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("workplace_support_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("private_note_encrypted", sa.Text(), nullable=False),
        sa.Column("employee_update_encrypted", sa.Text(), nullable=True),
        sa.Column("shared_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_workplace_case_notes_case", "workplace_case_notes", ["case_id", "created_at"])
    op.create_table(
        "workplace_appointments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("workplace_support_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", sa.Text(), sa.ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("starts_at", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("location_or_link_encrypted", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="scheduled"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_workplace_appointments_case", "workplace_appointments", ["case_id", "starts_at"])
    op.create_table(
        "workplace_messages",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("workplace_support_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body_encrypted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_workplace_messages_case", "workplace_messages", ["case_id", "created_at"])

    op.create_table(
        "guest_cases",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_code", sa.Text(), nullable=False, unique=True),
        sa.Column("counsellor_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("institution_id", sa.Text(), sa.ForeignKey("institutions.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending_consent"),
        sa.Column("consent_token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("consent_expires_at", sa.Text(), nullable=False),
        sa.Column("consent_method", sa.Text(), nullable=True),
        sa.Column("consented_at", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("closed_at", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "guest_platform_authorizations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("guest_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("handle_encrypted", sa.Text(), nullable=False),
        sa.Column("ownership_status", sa.Text(), nullable=False, server_default="visitor_authorized_unverified"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("case_id", "platform", name="uq_guest_case_platform"),
    )
    op.create_table(
        "guest_analysis_sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("guest_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("counsellor_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("results_encrypted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_guest_cases_counsellor", "guest_cases", ["counsellor_id", "created_at"])
    op.create_index("idx_guest_cases_expiry", "guest_cases", ["expires_at", "deleted_at"])
    op.create_table(
        "guest_case_notes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("guest_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("counsellor_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("note_type", sa.Text(), nullable=False, server_default="care_note"),
        sa.Column("private_note_encrypted", sa.Text(), nullable=False),
        sa.Column("visitor_update_encrypted", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_guest_case_notes_case", "guest_case_notes", ["case_id", "created_at"])

    op.create_table(
        "voice_support_sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_session_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="created"),
        sa.Column("consented_at", sa.Text(), nullable=False),
        sa.Column("consent_version", sa.Text(), nullable=False, server_default="voice-v1"),
        sa.Column("exercise", sa.Text(), nullable=True),
        sa.Column("summary_encrypted", sa.Text(), nullable=True),
        sa.Column("safety_outcome", sa.Text(), nullable=False, server_default="none"),
        sa.Column("alert_recipient_id", sa.Text(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("alert_delivery_status", sa.Text(), nullable=True),
        sa.Column("alert_acknowledged_at", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("ended_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_voice_sessions_user", "voice_support_sessions", ["user_id", "created_at"])
    op.create_index("idx_voice_alert_recipient", "voice_support_sessions", ["alert_recipient_id", "alert_delivery_status"])


def downgrade() -> None:
    op.drop_index("idx_voice_alert_recipient", table_name="voice_support_sessions")
    op.drop_index("idx_voice_sessions_user", table_name="voice_support_sessions")
    op.drop_table("voice_support_sessions")
    op.drop_index("idx_guest_case_notes_case", table_name="guest_case_notes")
    op.drop_table("guest_case_notes")
    op.drop_index("idx_workplace_messages_case", table_name="workplace_messages")
    op.drop_table("workplace_messages")
    op.drop_index("idx_workplace_appointments_case", table_name="workplace_appointments")
    op.drop_table("workplace_appointments")
    op.drop_index("idx_guest_cases_expiry", table_name="guest_cases")
    op.drop_index("idx_guest_cases_counsellor", table_name="guest_cases")
    op.drop_table("guest_analysis_sessions")
    op.drop_table("guest_platform_authorizations")
    op.drop_table("guest_cases")
    op.drop_index("idx_workplace_case_notes_case", table_name="workplace_case_notes")
    op.drop_table("workplace_case_notes")
    with op.batch_alter_table("workplace_settings") as batch:
        for column in ("archived_at", "policy_status", "retention_days", "employee_population_range", "privacy_contact_encrypted"):
            batch.drop_column(column)
