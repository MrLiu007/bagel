"""add intel_item.category for fixed taxonomy filtering

Revision ID: 0002_category
Revises: 0001_initial
Create Date: 2026-08-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_category"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("intel_item", sa.Column("category", sa.String(length=64), nullable=True))
    op.create_index("ix_intel_item_category", "intel_item", ["category"])


def downgrade() -> None:
    op.drop_index("ix_intel_item_category", table_name="intel_item")
    op.drop_column("intel_item", "category")
