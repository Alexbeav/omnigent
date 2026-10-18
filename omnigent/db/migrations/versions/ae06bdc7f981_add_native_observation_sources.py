"""Persist bounded passive native metadata separately from conversations."""

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "ae06bdc7f981"
down_revision: str | None = "mm1a2b3c4d5e"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "native_observation_sources",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("host_id", Uuid16(), nullable=False),
        sa.Column("harness", sa.String(16), nullable=False),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column("account_generation", sa.String(32), nullable=True),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("received_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "host_id", "harness"),
    )


def downgrade() -> None:
    op.drop_table("native_observation_sources")
