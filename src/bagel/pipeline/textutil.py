"""Plain-text helpers for display and classification."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", value))
    return _WS_RE.sub(" ", text).strip()


def truncate(value: str | None, limit: int = 160) -> str:
    text = strip_html(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def headline_from_body(value: str | None, *, limit: int = 48) -> str:
    """Build a list title from long social-post body (Weibo etc. have no real title)."""
    text = strip_html(value)
    if not text:
        return ""
    # Prefer a natural break before a hashtag cluster when the lead is long enough.
    hash_at = text.find("#")
    if 12 <= hash_at <= limit:
        lead = text[:hash_at].rstrip(" ，,、;；")
        if lead:
            return truncate(lead, limit)
    return truncate(text, limit)


def split_title_and_body(title: str | None, body: str | None) -> tuple[str, str]:
    """Avoid identical title/body for social posts; return (display_title, display_body)."""
    t = strip_html(title)
    b = strip_html(body)
    if not t and not b:
        return "", ""
    if not b:
        return t, ""
    if not t:
        return headline_from_body(b), b
    if t == b:
        # Short posts: show once as title. Longer: short title + full body.
        if len(b) <= 48:
            return b, ""
        return headline_from_body(b), b
    return t, b


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    local = value.astimezone()
    return local.strftime("%Y-%m-%d %H:%M")


def clip(value: str | None, limit: int) -> str | None:
    """Hard-truncate string fields to DB column limits (None-safe)."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit]
