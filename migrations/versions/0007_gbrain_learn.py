"""add gbrain_learn_event for flashcard learning logs

Revision ID: 0007_gbrain_learn
Revises: 0006_wiki_index
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_gbrain_learn"
down_revision: Union[str, Sequence[str], None] = "0006_wiki_index"
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
    if not _has_table("gbrain_learn_event"):
        json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
        op.create_table(
            "gbrain_learn_event",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("owner_id", sa.Uuid(), nullable=True),
            sa.Column("node_key", sa.String(length=128), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("metadata", json_type, nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["owner_id"], ["app_user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for ix, cols in (
        ("ix_gbrain_learn_event_owner_id", ["owner_id"]),
        ("ix_gbrain_learn_event_node_key", ["node_key"]),
        ("ix_gbrain_learn_event_action", ["action"]),
        ("ix_gbrain_learn_event_created_at", ["created_at"]),
    ):
        if not _has_index(ix):
            op.create_index(ix, "gbrain_learn_event", cols)


def downgrade() -> None:
    if not _has_table("gbrain_learn_event"):
        return
    for ix in (
        "ix_gbrain_learn_event_created_at",
        "ix_gbrain_learn_event_action",
        "ix_gbrain_learn_event_node_key",
        "ix_gbrain_learn_event_owner_id",
    ):
        if _has_index(ix):
            op.drop_index(ix, table_name="gbrain_learn_event")
    op.drop_table("gbrain_learn_event")
