"""Add an isolated demo mode for workplace onboarding."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workplace_settings") as batch:
        batch.add_column(
            sa.Column("demo_mode", sa.Integer(), nullable=False, server_default="0")
        )
    with op.batch_alter_table("workplace_provider_credentials") as batch:
        batch.add_column(
            sa.Column("demo_only", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("license_state_encrypted", sa.Text(), nullable=True))
    with op.batch_alter_table("workplace_provider_credential_history") as batch:
        batch.add_column(sa.Column("license_state_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workplace_provider_credential_history") as batch:
        batch.drop_column("license_state_encrypted")
    with op.batch_alter_table("workplace_provider_credentials") as batch:
        batch.drop_column("license_state_encrypted")
        batch.drop_column("demo_only")
    with op.batch_alter_table("workplace_settings") as batch:
        batch.drop_column("demo_mode")
