"""Expand Memory Weaver into a collaborative archive platform.

Revision ID: 20260724_05
Revises: 20260722_04
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260724_05"
down_revision: str | None = "20260722_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stories", sa.Column("location", sa.String(255)))
    op.add_column("stories", sa.Column("latitude", sa.Float()))
    op.add_column("stories", sa.Column("longitude", sa.Float()))
    op.add_column("stories", sa.Column("language", sa.String(40)))
    op.add_column("stories", sa.Column("original_content", sa.Text()))
    op.add_column("stories", sa.Column("updated_at", sa.BigInteger()))
    op.add_column("stories", sa.Column("deleted_at", sa.BigInteger()))
    op.create_index("ix_stories_updated_at", "stories", ["updated_at"])
    op.create_index("ix_stories_deleted_at", "stories", ["deleted_at"])
    op.execute("UPDATE stories SET updated_at = created_at WHERE updated_at IS NULL")
    op.add_column(
        "family_links",
        sa.Column(
            "role", sa.String(30), nullable=False, server_default=sa.text("'viewer'")
        ),
    )

    op.create_table(
        "story_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("editor_user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(140), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("year", sa.Integer()),
        sa.Column("location", sa.String(255)),
        sa.Column("language", sa.String(40)),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["editor_user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_story_revisions_story_id", "story_revisions", ["story_id"])

    op.create_table(
        "people",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("linked_user_id", sa.Integer()),
        sa.Column("parent_id", sa.Integer()),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("relation", sa.String(80)),
        sa.Column("birth_year", sa.Integer()),
        sa.Column("death_year", sa.Integer()),
        sa.Column("bio", sa.Text()),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_id"], ["people.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_people_owner_user_id", "people", ["owner_user_id"])
    op.create_index("ix_people_linked_user_id", "people", ["linked_user_id"])
    op.create_index("ix_people_parent_id", "people", ["parent_id"])

    op.create_table(
        "story_people",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("story_id", "person_id", name="uq_story_person"),
    )
    op.create_index("ix_story_people_story_id", "story_people", ["story_id"])
    op.create_index("ix_story_people_person_id", "story_people", ["person_id"])

    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("story_id", sa.Integer()),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("mime_type", sa.String(80), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("caption", sa.String(500)),
        sa.Column("location", sa.String(255)),
        sa.Column("taken_at", sa.String(40)),
        sa.Column("transcript", sa.Text()),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_media_assets_owner_user_id", "media_assets", ["owner_user_id"])
    op.create_index("ix_media_assets_story_id", "media_assets", ["story_id"])

    op.create_table(
        "albums",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(140), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_albums_owner_user_id", "albums", ["owner_user_id"])
    op.create_table(
        "album_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("album_id", sa.Integer(), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["album_id"], ["albums.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("album_id", "media_id", name="uq_album_media"),
    )
    op.create_index("ix_album_items_album_id", "album_items", ["album_id"])
    op.create_index("ix_album_items_media_id", "album_items", ["media_id"])

    op.create_table(
        "memory_capsules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("recipient_user_id", sa.Integer()),
        sa.Column("title", sa.String(140), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("unlock_at", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_memory_capsules_owner_user_id", "memory_capsules", ["owner_user_id"]
    )
    op.create_index(
        "ix_memory_capsules_recipient_user_id", "memory_capsules", ["recipient_user_id"]
    )
    op.create_index("ix_memory_capsules_unlock_at", "memory_capsules", ["unlock_at"])

    op.create_table(
        "story_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_story_comments_story_id", "story_comments", ["story_id"])
    op.create_index("ix_story_comments_user_id", "story_comments", ["user_id"])

    op.create_table(
        "story_reactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("emoji", sa.String(16), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("story_id", "user_id", name="uq_story_reaction_user"),
    )
    op.create_index("ix_story_reactions_story_id", "story_reactions", ["story_id"])
    op.create_index("ix_story_reactions_user_id", "story_reactions", ["user_id"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("link", sa.String(500)),
        sa.Column("read_at", sa.BigInteger()),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.create_table(
        "drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "key", name="uq_draft_user_key"),
    )
    op.create_index("ix_drafts_user_id", "drafts", ["user_id"])

    op.create_table(
        "story_translations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(40), nullable=False),
        sa.Column("title", sa.String(140), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "story_id", "language", name="uq_story_translation_language"
        ),
    )
    op.create_index(
        "ix_story_translations_story_id", "story_translations", ["story_id"]
    )

    op.create_table(
        "interview_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="participant"),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["interview_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("session_id", "user_id", name="uq_interview_participant"),
    )
    op.create_index(
        "ix_interview_participants_session_id", "interview_participants", ["session_id"]
    )
    op.create_index(
        "ix_interview_participants_user_id", "interview_participants", ["user_id"]
    )


def downgrade() -> None:
    for table in (
        "interview_participants",
        "story_translations",
        "drafts",
        "notifications",
        "story_reactions",
        "story_comments",
        "memory_capsules",
        "album_items",
        "albums",
        "media_assets",
        "story_people",
        "people",
        "story_revisions",
    ):
        op.drop_table(table)
    op.drop_column("family_links", "role")
    for column in (
        "deleted_at",
        "updated_at",
        "original_content",
        "language",
        "longitude",
        "latitude",
        "location",
    ):
        op.drop_column("stories", column)
