"""add app_user (required before wiki_page / gbrain FKs)

Revision ID: 0005a_app_user
Revises: 0005_search_event
Create Date: 2026-09-03

`app_user` was historically created only via SQLite ``create_all`` and never
landed in Alembic. Postgres Compose deploys run ``alembic upgrade head`` and
failed at 0006 when creating ``wiki_page`` FK → ``app_user``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005a_app_user"
down_revision: Union[str, Sequence[str], None] = "0005_search_event"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    if _has_table("app_user"):
        return
    op.create_table(
        "app_user",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_app_user_username"),
    )


def downgrade() -> None:
    if _has_table("app_user"):
        op.drop_table("app_user")
