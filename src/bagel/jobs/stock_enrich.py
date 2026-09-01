"""Backfill stock enrichment for existing STOCK_NEWS rows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType
from bagel.services import stock_events
from bagel.settings import get_settings
from bagel.storage.repositories import ItemRepository

ProgressCallback = Callable[..., None]


def run_enrich_stocks(
    session: Session,
    *,
    on_progress: ProgressCallback | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.enable_stock_enrichment:
        return {
            "status": "FAILED",
            "error": "股票 enrichment 已关闭（ENABLE_STOCK_ENRICHMENT）",
            "items_updated": 0,
            "items_found": 0,
        }

    repo = ItemRepository(session)
    rows = list(
        repo.list_by_status(
            ItemStatus.CANDIDATE,
            item_type=ItemType.STOCK_NEWS,
            limit=limit,
            offset=0,
        )
    )
    total = len(rows)
    updated = 0
    if on_progress:
        on_progress(current=0, total=max(total, 1), message=f"准备 enrichment {total} 条…")

    for i, item in enumerate(rows, start=1):
        before = stock_events.stock_meta(item).get("extractor_version")
        stock_events.ensure_enriched(item)
        after = stock_events.stock_meta(item).get("extractor_version")
        if after and after != before:
            updated += 1
        elif not before and after:
            updated += 1
        if on_progress and (i % 20 == 0 or i == total):
            on_progress(current=i, total=total, message=f"已处理 {i}/{total}")

    session.flush()
    return {
        "status": "SUCCESS",
        "items_found": total,
        "items_updated": updated,
        "items_created": 0,
        "items_skipped": max(0, total - updated),
    }
