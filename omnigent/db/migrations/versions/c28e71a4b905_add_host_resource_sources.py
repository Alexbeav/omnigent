"""Persist the latest bounded host resource sample."""

import sqlalchemy as sa
from alembic import op

from omnigent.db.db_models import Uuid16

revision: str = "c28e71a4b905"
down_revision: str | None = "ae06bdc7f981"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "host_resource_sources",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("host_id", Uuid16(), nullable=False),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column("account_generation", sa.String(32), nullable=True),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("received_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "host_id"),
    )


def downgrade() -> None:
    op.drop_table("host_resource_sources")
