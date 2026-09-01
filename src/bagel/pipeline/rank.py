"""Simple ranking by score / recency markers."""

from __future__ import annotations

from typing import Sequence

from bagel.domain.models import IntelItem


def rank_items(items: Sequence[IntelItem]) -> list[IntelItem]:
    return sorted(
        items,
        key=lambda i: (
            1 if i.is_top else 0,
            1 if i.is_deep_read else 0,
            i.published_at.timestamp() if i.published_at else 0.0,
            i.score,
        ),
        reverse=True,
    )
