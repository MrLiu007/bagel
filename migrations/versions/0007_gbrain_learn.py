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


def upgrade() -> None:
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
    op.create_index("ix_gbrain_learn_event_owner_id", "gbrain_learn_event", ["owner_id"])
    op.create_index("ix_gbrain_learn_event_node_key", "gbrain_learn_event", ["node_key"])
    op.create_index("ix_gbrain_learn_event_action", "gbrain_learn_event", ["action"])
    op.create_index("ix_gbrain_learn_event_created_at", "gbrain_learn_event", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_gbrain_learn_event_created_at", table_name="gbrain_learn_event")
    op.drop_index("ix_gbrain_learn_event_action", table_name="gbrain_learn_event")
    op.drop_index("ix_gbrain_learn_event_node_key", table_name="gbrain_learn_event")
    op.drop_index("ix_gbrain_learn_event_owner_id", table_name="gbrain_learn_event")
    op.drop_table("gbrain_learn_event")
