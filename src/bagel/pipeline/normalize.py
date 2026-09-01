"""Normalize collector payloads into `NormalizedItem` DTOs.

All collectors should funnel through helpers here (or equivalent) so URL
canonicalization and datetime parsing stay consistent before upsert.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import UUID

from bagel.domain.contracts import NormalizedItem
from bagel.domain.enums import ItemType, SourceType
from bagel.storage.repositories import canonicalize_url


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return parsedate_to_datetime(text).astimezone(UTC)
        except (TypeError, ValueError, IndexError):
            pass
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            return None
    return None


def from_rss_entry(
    entry: dict[str, Any],
    *,
    source_id: UUID | None,
    source_type: str = SourceType.RSS,
    feed_url: str | None = None,
    item_type: str = ItemType.NEWS,
) -> NormalizedItem | None:
    title = (entry.get("title") or "").strip()
    link = (entry.get("link") or entry.get("id") or "").strip()
    if not title or not link:
        return None

    summary = entry.get("summary") or entry.get("description")
    content = None
    if entry.get("content"):
        # feedparser content is list of dicts
        parts = entry["content"]
        if isinstance(parts, list) and parts:
            content = parts[0].get("value")
        elif isinstance(parts, str):
            content = parts

    published = (
        parse_datetime(entry.get("published"))
        or parse_datetime(entry.get("updated"))
    )
    # feedparser time.struct_time — prefer explicit parsed fields
    if published is None:
        for key in ("published_parsed", "updated_parsed"):
            struct = entry.get(key)
            if not struct:
                continue
            try:
                # struct_time or tuple
                published = datetime(*struct[:6], tzinfo=UTC)
                break
            except (TypeError, ValueError):
                pass

    return NormalizedItem(
        item_type=item_type or ItemType.NEWS,
        source_type=source_type,
        source_id=source_id,
        title=title,
        summary=summary,
        content=content,
        url=link,
        canonical_url=canonicalize_url(link),
        author=(entry.get("author") or None),
        language=None,
        published_at=published,
        external_id=str(entry.get("id") or link),
        metadata={"feed_url": feed_url} if feed_url else {},
        raw_payload=dict(entry) if isinstance(entry, dict) else {"entry": str(entry)},
    )
