"""add wiki_page + wiki_edge indexes for MD wiki compile

Revision ID: 0006_wiki_index
Revises: 0005a_app_user
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_wiki_index"
down_revision: Union[str, Sequence[str], None] = "0005a_app_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def _has_index(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table in insp.get_table_names():
        if any(ix["name"] == name for ix in insp.get_indexes(table)):
            return True
    return False


def upgrade() -> None:
    if not _has_table("wiki_page"):
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
    for ix, table, cols in (
        ("ix_wiki_page_slug", "wiki_page", ["slug"]),
        ("ix_wiki_page_kind", "wiki_page", ["kind"]),
        ("ix_wiki_page_owner_id", "wiki_page", ["owner_id"]),
        ("ix_wiki_page_intel_item_id", "wiki_page", ["intel_item_id"]),
        ("ix_wiki_page_topic_id", "wiki_page", ["topic_id"]),
    ):
        if not _has_index(ix):
            op.create_index(ix, table, cols)

    if not _has_table("wiki_edge"):
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
    for ix, table, cols in (
        ("ix_wiki_edge_owner_id", "wiki_edge", ["owner_id"]),
        ("ix_wiki_edge_source_key", "wiki_edge", ["source_key"]),
        ("ix_wiki_edge_target_key", "wiki_edge", ["target_key"]),
    ):
        if not _has_index(ix):
            op.create_index(ix, table, cols)


def downgrade() -> None:
    if _has_table("wiki_edge"):
        for ix in (
            "ix_wiki_edge_target_key",
            "ix_wiki_edge_source_key",
            "ix_wiki_edge_owner_id",
        ):
            if _has_index(ix):
                op.drop_index(ix, table_name="wiki_edge")
        op.drop_table("wiki_edge")
    if _has_table("wiki_page"):
        for ix in (
            "ix_wiki_page_topic_id",
            "ix_wiki_page_intel_item_id",
            "ix_wiki_page_owner_id",
            "ix_wiki_page_kind",
            "ix_wiki_page_slug",
        ):
            if _has_index(ix):
                op.drop_index(ix, table_name="wiki_page")
        op.drop_table("wiki_page")
