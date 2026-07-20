"""Add persistent per-user AI rate-limit events."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260721_02"
down_revision: Union[str, None] = "20260720_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rate_limit_events_user_id", "rate_limit_events", ["user_id"])
    op.create_index("ix_rate_limit_events_action", "rate_limit_events", ["action"])
    op.create_index(
        "ix_rate_limit_events_created_at", "rate_limit_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_rate_limit_events_created_at", table_name="rate_limit_events")
    op.drop_index("ix_rate_limit_events_action", table_name="rate_limit_events")
    op.drop_index("ix_rate_limit_events_user_id", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
