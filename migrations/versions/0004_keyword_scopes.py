"""add scopes column to intel_keyword_rule

Revision ID: 0004_keyword_scopes
Revises: 0003_monthly_brief
Create Date: 2026-09-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_keyword_scopes"
down_revision: Union[str, Sequence[str], None] = "0003_monthly_brief"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "intel_keyword_rule",
        sa.Column("scopes", sa.String(length=255), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("intel_keyword_rule", "scopes")
