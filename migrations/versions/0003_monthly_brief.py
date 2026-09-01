"""add intel_monthly_brief for monthly sharing briefs

Revision ID: 0003_monthly_brief
Revises: 0002_category
Create Date: 2026-08-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_monthly_brief"
down_revision: Union[str, Sequence[str], None] = "0002_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intel_monthly_brief",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("year_month", sa.String(length=7), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("template_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "generated_at",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year_month", "kind", name="uq_monthly_brief_month_kind"),
    )
    op.create_index("ix_intel_monthly_brief_year_month", "intel_monthly_brief", ["year_month"])
    op.create_index("ix_intel_monthly_brief_kind", "intel_monthly_brief", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_intel_monthly_brief_kind", table_name="intel_monthly_brief")
    op.drop_index("ix_intel_monthly_brief_year_month", table_name="intel_monthly_brief")
    op.drop_table("intel_monthly_brief")
