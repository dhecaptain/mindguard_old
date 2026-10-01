"""Add workplace commercial accounts, plan metadata and transition history."""

from typing import Sequence, Union
import re

from alembic import op
import sqlalchemy as sa

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workplace_commercial_accounts",
        sa.Column("company_id", sa.Text(), sa.ForeignKey("institutions.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="PILOT"),
        sa.Column("plan_key", sa.Text(), nullable=False, server_default="legacy_pilot"),
        sa.Column("capabilities_json", sa.Text(), nullable=True),
        sa.Column("contract_start_date", sa.Text(), nullable=True),
        sa.Column("contract_end_date", sa.Text(), nullable=True),
        sa.Column("billing_cycle", sa.Text(), nullable=True),
        sa.Column("population_band", sa.Text(), nullable=False, server_default="not_recorded"),
        sa.Column("renewal_date", sa.Text(), nullable=True),
        sa.Column("grace_period_end", sa.Text(), nullable=True),
        sa.Column("cancellation_effective_date", sa.Text(), nullable=True),
        sa.Column("cancellation_reason_encrypted", sa.Text(), nullable=True),
        sa.Column("terminated_at", sa.Text(), nullable=True),
        sa.Column("internal_reference_encrypted", sa.Text(), nullable=True),
        sa.Column("internal_notes_encrypted", sa.Text(), nullable=True),
        sa.Column("external_customer_reference", sa.Text(), nullable=True),
        sa.Column("external_subscription_reference", sa.Text(), nullable=True),
        sa.Column("billing_provider", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "workplace_commercial_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("company_id", sa.Text(), sa.ForeignKey("institutions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_user_id", sa.Text(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("previous_status", sa.Text(), nullable=True),
        sa.Column("new_status", sa.Text(), nullable=True),
        sa.Column("reason_encrypted", sa.Text(), nullable=True),
        sa.Column("reference_encrypted", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_workplace_commercial_events", "workplace_commercial_events", ["company_id", "occurred_at"])
    bind = op.get_bind()
    companies = bind.execute(sa.text(
        "SELECT i.id,i.created_at,i.updated_at,s.employee_population_range "
        "FROM institutions i JOIN workplace_settings s ON s.company_id=i.id WHERE lower(i.type)='company'"
    )).mappings()
    for company in companies:
        value = str(company["employee_population_range"] or "").strip().lower().replace(",", "")
        numbers = [int(part) for part in re.findall(r"\d+", value)]
        if "1000" in value or "more" in value or "+" in value or (numbers and max(numbers) > 1000):
            band = "1000+"
        elif numbers:
            upper = max(numbers)
            band = "1-50" if upper <= 50 else "51-200" if upper <= 200 else "201-500" if upper <= 500 else "501-1000"
        else:
            band = "not_recorded"
        created_at = company["created_at"]
        bind.execute(sa.text(
            "INSERT INTO workplace_commercial_accounts "
            "(company_id,status,plan_key,contract_start_date,population_band,created_at,updated_at) "
            "VALUES (:company_id,'PILOT','legacy_pilot',:start_date,:band,:created_at,:updated_at)"
        ), {"company_id": company["id"], "start_date": str(created_at or "")[:10], "band": band,
            "created_at": created_at, "updated_at": company["updated_at"] or created_at})


def downgrade() -> None:
    op.drop_index("idx_workplace_commercial_events", table_name="workplace_commercial_events")
    op.drop_table("workplace_commercial_events")
    op.drop_table("workplace_commercial_accounts")
