"""Recency helpers — prefer recently published items on each collect."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

_DATE_FILTER_RE = re.compile(r"\b(created|pushed|updated):>", re.IGNORECASE)


def lookback_cutoff(days: int, *, now: datetime | None = None) -> datetime:
    days = max(1, int(days))
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now - timedelta(days=days)


def is_within_lookback(
    published_at: datetime | None,
    *,
    days: int,
    now: datetime | None = None,
    keep_unknown: bool = False,
) -> bool:
    """Return whether an item should be kept for a recent-only collect."""
    if published_at is None:
        return keep_unknown
    cutoff = lookback_cutoff(days, now=now)
    dt = published_at if published_at.tzinfo else published_at.replace(tzinfo=UTC)
    return dt >= cutoff


def github_query_with_recency(query: str, *, days: int, now: datetime | None = None) -> str:
    """Append ``pushed:>YYYY-MM-DD`` when the query has no explicit date filter.

    Do **not** wrap the base query in parentheses — GitHub Search returns HTTP 422
    for many ``(a OR b …) pushed:>date`` forms. Appending the qualifier is enough
    for qualifier scoping on the whole query string.
    """
    q = (query or "").strip()
    if not q or _DATE_FILTER_RE.search(q):
        return q
    since = lookback_cutoff(days, now=now).strftime("%Y-%m-%d")
    return f"{q} pushed:>{since}"


def sort_key_published(published_at: datetime | None) -> float:
    if published_at is None:
        return 0.0
    dt = published_at if published_at.tzinfo else published_at.replace(tzinfo=UTC)
    return dt.timestamp()
