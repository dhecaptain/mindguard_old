"""baseline: reconcile the full MindGuard schema

Revision ID: 0001
Revises:
Create Date: 2026-08-05

This is the adoption baseline. It reconciles the schema that previously lived
as ad-hoc ``CREATE TABLE IF NOT EXISTS`` / ``ALTER TABLE`` statements inside
``backend.database.init_db`` into Alembic:

  * Fresh databases get the complete schema.
  * Pre-existing databases (created before Alembic was adopted) are brought in
    line: existing tables are left untouched, and the formerly ad-hoc additive
    columns are added where missing.

Every statement is guarded so the migration is idempotent, which is required
because existing deployments have never been versioned.

Revision ID: 0001
Revises:
Create Date: 2026-08-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in _inspector().get_columns(table))


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if _has_column(table, column.name):
        return
    op.add_column(table, column)


def upgrade() -> None:
    # ── Core (users first: referenced by most other tables) ─────────────
    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("email", sa.Text(), nullable=False, unique=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("role_type", sa.Text(), nullable=False, server_default="student"),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("avatar_url", sa.Text(), server_default=""),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("terms_accepted_at", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
    _add_column_if_missing("users", sa.Column("dob", sa.Text(), nullable=True))
    _add_column_if_missing("users", sa.Column("parent_email", sa.Text(), nullable=True))
    _add_column_if_missing(
        "users", sa.Column("referral_code", sa.Text(), nullable=True)
    )
    _add_column_if_missing("users", sa.Column("referred_by", sa.Text(), nullable=True))
    _add_column_if_missing(
        "users", sa.Column("permissions_json", sa.Text(), server_default="[]")
    )

    if not _has_table("analyses"):
        op.create_table(
            "analyses",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("platform", sa.Text(), nullable=False, server_default="text"),
            sa.Column("text", sa.Text(), nullable=True),
            sa.Column("prob", sa.Float(), nullable=False),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
        )

    if not _has_table("referrals"):
        op.create_table(
            "referrals",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "counsellor_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column(
                "student_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("urgency", sa.Text(), nullable=False, server_default="medium"),
            sa.Column("status", sa.Text(), nullable=False, server_default="open"),
            sa.Column("notes", sa.Text(), server_default=""),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )

    if not _has_table("communications"):
        op.create_table(
            "communications",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "sender_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column(
                "receiver_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("read", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.Text(), nullable=False),
        )

    if not _has_table("notifications"):
        op.create_table(
            "notifications",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("type", sa.Text(), nullable=False, server_default="general"),
            sa.Column("read", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.Text(), nullable=False),
        )

    if not _has_table("institutions"):
        op.create_table(
            "institutions",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("type", sa.Text(), server_default="university"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("retention_days", sa.Integer(), server_default="30"),
            sa.Column("alert_threshold", sa.Float(), server_default="0.65"),
            sa.Column("confidence_floor", sa.Float(), server_default="0.70"),
        )
    _add_column_if_missing(
        "institutions",
        sa.Column("minor_age_threshold", sa.Integer(), server_default="18"),
    )
    _add_column_if_missing(
        "institutions", sa.Column("consent_template_id", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "institutions",
        sa.Column("consent_reminder_days", sa.Text(), server_default="[7,14]"),
    )
    _add_column_if_missing(
        "institutions",
        sa.Column("consent_expiry_days", sa.Integer(), server_default="30"),
    )

    if not _has_table("consents"):
        op.create_table(
            "consents",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "student_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column(
                "counsellor_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("recipient_email", sa.Text(), nullable=False),
            sa.Column(
                "recipient_role", sa.Text(), nullable=False, server_default="student"
            ),
            sa.Column("status", sa.Text(), nullable=False, server_default="DRAFT"),
            sa.Column("platforms_json", sa.Text(), server_default="[]"),
            sa.Column("mode", sa.Text(), server_default="ON_DEMAND"),
            sa.Column("document_version", sa.Text(), server_default="v2.0"),
            sa.Column("magic_token", sa.Text(), nullable=True),
            sa.Column("magic_token_expires_at", sa.Text(), nullable=True),
            sa.Column("signature_name", sa.Text(), nullable=True),
            sa.Column("signature_ip", sa.Text(), nullable=True),
            sa.Column("dispatched_at", sa.Text(), nullable=True),
            sa.Column("viewed_at", sa.Text(), nullable=True),
            sa.Column("accepted_at", sa.Text(), nullable=True),
            sa.Column("declined_at", sa.Text(), nullable=True),
            sa.Column("revoked_at", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )
    _add_column_if_missing(
        "consents", sa.Column("signed_token_hash", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "consents", sa.Column("response_ip", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "consents", sa.Column("response_user_agent", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "consents", sa.Column("reminders_sent", sa.Integer(), server_default="0")
    )
    _add_column_if_missing(
        "consents", sa.Column("template_version", sa.Text(), server_default="1.0.0")
    )
    _add_column_if_missing("consents", sa.Column("notes", sa.Text(), server_default=""))

    if not _has_table("linked_accounts"):
        op.create_table(
            "linked_accounts",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "student_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column(
                "consent_id", sa.Text(), sa.ForeignKey("consents.id"), nullable=True
            ),
            sa.Column("platform", sa.Text(), nullable=False),
            sa.Column("mode", sa.Text(), server_default="handle"),
            sa.Column("handle", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), server_default="active"),
            sa.Column("last_synced_at", sa.Text(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )

    if not _has_table("alerts"):
        op.create_table(
            "alerts",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "student_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column(
                "counsellor_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("fired_at", sa.Text(), nullable=False),
            sa.Column("risk_score", sa.Float(), nullable=False),
            sa.Column("threshold_at_fire", sa.Float(), nullable=False),
            sa.Column("platform", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="OPEN"),
            sa.Column("disposition", sa.Text(), nullable=True),
            sa.Column("disposition_reason", sa.Text(), nullable=True),
            sa.Column("disposition_note", sa.Text(), nullable=True),
            sa.Column("dispositioned_by", sa.Text(), nullable=True),
            sa.Column("dispositioned_at", sa.Text(), nullable=True),
            sa.Column("supersedes_id", sa.Text(), nullable=True),
            sa.Column("cooldown_until", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )

    if not _has_table("audit_log"):
        op.create_table(
            "audit_log",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("actor_id", sa.Text(), nullable=True),
            sa.Column("actor_role", sa.Text(), nullable=True),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("target_type", sa.Text(), nullable=True),
            sa.Column("target_id", sa.Text(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("ip", sa.Text(), nullable=True),
            sa.Column("occurred_at", sa.Text(), nullable=False),
        )

    if not _has_table("notes"):
        op.create_table(
            "notes",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "student_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column(
                "author_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )

    if not _has_table("rolling_risk"):
        op.create_table(
            "rolling_risk",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "student_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("computed_at", sa.Text(), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("window_days", sa.Integer(), server_default="14"),
            sa.Column("top_platform", sa.Text(), nullable=True),
            sa.Column("n_posts", sa.Integer(), server_default="0"),
        )

    if not _has_table("groups"):
        op.create_table(
            "groups",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), server_default=""),
            sa.Column("avatar_url", sa.Text(), server_default=""),
            sa.Column(
                "created_by", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )

    if not _has_table("group_members"):
        op.create_table(
            "group_members",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "group_id", sa.Text(), sa.ForeignKey("groups.id"), nullable=False
            ),
            sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("role", sa.Text(), nullable=False, server_default="member"),
            sa.Column("joined_at", sa.Text(), nullable=False),
            sa.UniqueConstraint("group_id", "user_id"),
        )

    if not _has_table("group_messages"):
        op.create_table(
            "group_messages",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "group_id", sa.Text(), sa.ForeignKey("groups.id"), nullable=False
            ),
            sa.Column(
                "sender_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
        )

    if not _has_table("group_message_read"):
        op.create_table(
            "group_message_read",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "message_id",
                sa.Text(),
                sa.ForeignKey("group_messages.id"),
                nullable=False,
            ),
            sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("read_at", sa.Text(), nullable=False),
            sa.UniqueConstraint("message_id", "user_id"),
        )

    if not _has_table("notification_preferences"):
        op.create_table(
            "notification_preferences",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("type", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("muted_groups", sa.Text(), server_default="[]"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.UniqueConstraint("user_id", "type"),
        )

    # ── Consent & roster data model (Delivery Brief §3) ─────────────────
    if not _has_table("students"):
        op.create_table(
            "students",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "institution_id",
                sa.Text(),
                sa.ForeignKey("institutions.id"),
                nullable=True,
            ),
            sa.Column("student_id_hash", sa.Text(), nullable=False, unique=True),
            sa.Column("first_name_encrypted", sa.Text(), nullable=False),
            sa.Column("email_encrypted", sa.Text(), nullable=False),
            sa.Column("date_of_birth_encrypted", sa.Text(), nullable=False),
            sa.Column("is_minor", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("parent_email_encrypted", sa.Text(), nullable=True),
            sa.Column("parent_first_name_encrypted", sa.Text(), nullable=True),
            sa.Column("grade_level", sa.Text(), nullable=True),
            sa.Column(
                "current_consent_id",
                sa.Text(),
                sa.ForeignKey("consents.id"),
                nullable=True,
            ),
            sa.Column(
                "created_by", sa.Text(), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.Column("deleted_at", sa.Text(), nullable=True),
        )

    if not _has_table("consent_templates"):
        op.create_table(
            "consent_templates",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "institution_id",
                sa.Text(),
                sa.ForeignKey("institutions.id"),
                nullable=True,
            ),
            sa.Column("version", sa.Text(), nullable=False, server_default="1.0.0"),
            sa.Column("language", sa.Text(), nullable=False, server_default="en"),
            sa.Column("subject_email_html", sa.Text(), nullable=True),
            sa.Column("parent_email_html", sa.Text(), nullable=True),
            sa.Column("consent_page_html", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )

    if not _has_table("consent_events"):
        op.create_table(
            "consent_events",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column(
                "consent_id", sa.Text(), sa.ForeignKey("consents.id"), nullable=False
            ),
            sa.Column("event_type", sa.Text(), nullable=False),
            sa.Column("actor_type", sa.Text(), nullable=False, server_default="system"),
            sa.Column("actor_id", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )

    if not _has_table("demo_requests"):
        op.create_table(
            "demo_requests",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("full_name", sa.Text(), nullable=False),
            sa.Column("work_email", sa.Text(), nullable=False),
            sa.Column("organisation", sa.Text(), nullable=False),
            sa.Column("role_title", sa.Text(), nullable=True),
            sa.Column(
                "organisation_type", sa.Text(), nullable=False, server_default="other"
            ),
            sa.Column("country", sa.Text(), nullable=True),
            sa.Column("student_count_range", sa.Text(), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("heard_about_us", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="new"),
            sa.Column(
                "assigned_to", sa.Text(), sa.ForeignKey("users.id"), nullable=True
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "consent_to_contact", sa.Integer(), nullable=False, server_default="1"
            ),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )

    if not _has_table("email_events"):
        op.create_table(
            "email_events",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("related_type", sa.Text(), nullable=False),
            sa.Column("related_id", sa.Text(), nullable=True),
            sa.Column("event", sa.Text(), nullable=False),
            sa.Column("esp_message_id", sa.Text(), nullable=True),
            sa.Column("recipient_email", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    """Baseline has no meaningful downgrade: existing deployments predate
    Alembic and dropping tables would destroy data. For fresh databases the
    correct rollback is to delete the database file."""
    pass
