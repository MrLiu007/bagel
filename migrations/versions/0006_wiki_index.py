"""add wiki_page + wiki_edge indexes for MD wiki compile

Revision ID: 0006_wiki_index
Revises: 0005_search_event
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_wiki_index"
down_revision: Union[str, Sequence[str], None] = "0005_search_event"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wiki_page",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("rel_path", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("intel_item_id", sa.Uuid(), nullable=True),
        sa.Column("topic_id", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "compiled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["intel_item_id"], ["intel_item.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rel_path", name="uq_wiki_page_rel_path"),
    )
    op.create_index("ix_wiki_page_slug", "wiki_page", ["slug"])
    op.create_index("ix_wiki_page_kind", "wiki_page", ["kind"])
    op.create_index("ix_wiki_page_owner_id", "wiki_page", ["owner_id"])
    op.create_index("ix_wiki_page_intel_item_id", "wiki_page", ["intel_item_id"])
    op.create_index("ix_wiki_page_topic_id", "wiki_page", ["topic_id"])

    op.create_table(
        "wiki_edge",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column("target_key", sa.String(length=128), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_key",
            "target_key",
            "relation",
            name="uq_wiki_edge_src_tgt_rel",
        ),
    )
    op.create_index("ix_wiki_edge_owner_id", "wiki_edge", ["owner_id"])
    op.create_index("ix_wiki_edge_source_key", "wiki_edge", ["source_key"])
    op.create_index("ix_wiki_edge_target_key", "wiki_edge", ["target_key"])


def downgrade() -> None:
    op.drop_index("ix_wiki_edge_target_key", table_name="wiki_edge")
    op.drop_index("ix_wiki_edge_source_key", table_name="wiki_edge")
    op.drop_index("ix_wiki_edge_owner_id", table_name="wiki_edge")
    op.drop_table("wiki_edge")
    op.drop_index("ix_wiki_page_topic_id", table_name="wiki_page")
    op.drop_index("ix_wiki_page_intel_item_id", table_name="wiki_page")
    op.drop_index("ix_wiki_page_owner_id", table_name="wiki_page")
    op.drop_index("ix_wiki_page_kind", table_name="wiki_page")
    op.drop_index("ix_wiki_page_slug", table_name="wiki_page")
    op.drop_table("wiki_page")
