"""Shared Jinja2 environment for all HTML routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.templating import Jinja2Templates

from bagel.domain.enums import ItemType
from bagel.pipeline.textutil import (
    format_datetime,
    split_title_and_body,
    strip_html,
    truncate,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["plain"] = truncate
templates.env.filters["fmt_dt"] = format_datetime


def present_item(item, *, preview: bool | None = None) -> dict:
    """View-model so templates do not depend on custom filters.

    Lists show full summary/content. Media posts dedupe identical title/body.
    """
    _ = preview
    raw_title = strip_html(getattr(item, "title", None) or "")
    raw_body = strip_html(item.summary or item.content or "")
    title, body = split_title_and_body(raw_title, raw_body)

    item_type = getattr(item, "item_type", None)

    stock_meta = {}
    meta = getattr(item, "metadata_", None) or {}
    if isinstance(meta, dict) and isinstance(meta.get("stock"), dict):
        stock_meta = meta["stock"]
    tickers = []
    for t in stock_meta.get("tickers") or []:
        if isinstance(t, dict) and t.get("symbol"):
            tickers.append(
                {
                    "symbol": t["symbol"],
                    "name": t.get("name") or t["symbol"],
                }
            )
    sentiment = stock_meta.get("sentiment") or ""
    themes = [str(x) for x in (stock_meta.get("themes") or []) if x][:4]

    published = item.published_at
    if published is not None:
        time_label = format_datetime(published)
        time_prefix = "发布 "
    else:
        # Do not fall back to入库时间 — that misleads “latest by publish time”.
        time_label = "时间未知"
        time_prefix = ""
    first_seen = getattr(item, "first_seen_at", None)
    is_new = False
    if first_seen is not None:
        fs = first_seen if first_seen.tzinfo else first_seen.replace(tzinfo=UTC)
        is_new = fs >= datetime.now(UTC) - timedelta(hours=24)

    return {
        "id": item.id,
        "url": item.url,
        "title": title or raw_title,
        "category": item.category,
        "author": getattr(item, "author", None) or "",
        "tags": list(item.tags or []),
        "summary": body or raw_body,
        "show_related": item_type
        in {
            ItemType.NEWS,
            ItemType.PAPER,
            ItemType.STOCK_NEWS,
            ItemType.GITHUB_REPO,
            ItemType.GITHUB_RELEASE,
            ItemType.MEDIA_POST,
        },
        "tickers": tickers,
        "sentiment": sentiment,
        "themes": themes,
        "time_label": time_label,
        "time_prefix": time_prefix,
        "is_favorite": bool(item.is_favorite),
        "is_top": bool(item.is_top),
        "is_deep_read": bool(item.is_deep_read),
        "is_new": is_new,
        "item_type": item.item_type,
        "status": item.status,
    }
