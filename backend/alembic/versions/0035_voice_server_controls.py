"""Add server-controlled voice call state and realtime sideband ownership."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("voice_support_sessions") as batch:
        batch.add_column(sa.Column("client_secret_encrypted", sa.Text(), nullable=True))
        batch.add_column(sa.Column("provider_call_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("sideband_connected_at", sa.Text(), nullable=True))
        batch.add_column(sa.Column("started_at", sa.Text(), nullable=True))
        batch.add_column(sa.Column("duration_seconds", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("failure_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("sideband_worker_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("sideband_lease_until", sa.Text(), nullable=True))

    op.create_index(
        "uq_voice_provider_call_id",
        "voice_support_sessions",
        ["provider_call_id"],
        unique=True,
    )
    # Any pre-existing active call was created without a trusted server-side
    # control channel. Do not silently upgrade it to a monitored session.
    op.execute(
        "UPDATE voice_support_sessions "
        "SET status='failed', failure_reason='server_side_controls_unavailable', "
        "ended_at=COALESCE(ended_at, updated_at) "
        "WHERE status='active' AND provider_call_id IS NULL"
    )


def downgrade() -> None:
    op.drop_index("uq_voice_provider_call_id", table_name="voice_support_sessions")
    with op.batch_alter_table("voice_support_sessions") as batch:
        for column in (
            "sideband_lease_until",
            "sideband_worker_id",
            "failure_reason",
            "duration_seconds",
            "started_at",
            "sideband_connected_at",
            "provider_call_id",
            "client_secret_encrypted",
        ):
            batch.drop_column(column)
