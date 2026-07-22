"""Add private story image attachments.

Revision ID: 20260722_04
Revises: 20260721_03
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260722_04"
down_revision: str | None = "20260721_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_images",
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=40), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("image_data", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["stories.id"],
            name="fk_story_images_story_id_stories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("story_id", name="pk_story_images"),
    )


def downgrade() -> None:
    op.drop_table("story_images")
