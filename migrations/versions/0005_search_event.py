"""add intel_search_event for analytics and keyword growth

Revision ID: 0005_search_event
Revises: 0004_keyword_scopes
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_search_event"
down_revision: Union[str, Sequence[str], None] = "0004_keyword_scopes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intel_search_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("query", sa.String(length=255), nullable=False),
        sa.Column("item_types", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="web"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_intel_search_event_query", "intel_search_event", ["query"])
    op.create_index("ix_intel_search_event_owner_id", "intel_search_event", ["owner_id"])
    op.create_index("ix_intel_search_event_created_at", "intel_search_event", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_intel_search_event_created_at", table_name="intel_search_event")
    op.drop_index("ix_intel_search_event_owner_id", table_name="intel_search_event")
    op.drop_index("ix_intel_search_event_query", table_name="intel_search_event")
    op.drop_table("intel_search_event")
