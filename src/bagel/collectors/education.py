"""Education / OCW collectors — university open learning RSS feeds."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import feedparser
import httpx

from bagel.settings import get_settings

# Many .edu / CDN hosts block custom bot UAs (403). Prefer a browser-like UA.
USER_AGENT = (
    "Mozilla/5.0 (compatible; BagelEducation/0.3; +https://github.com/MrLiu007/bagel) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8"


@dataclass
class EducationRecord:
    title: str
    url: str
    summary: str
    authors: str
    published_at: datetime | None
    source_name: str
    external_id: str
    institution: str = ""
    tags: list[str] | None = None
    raw: dict[str, Any] | None = None


def _client(timeout: float = 40.0) -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=timeout,
        proxy=settings.proxy_url or None,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": _ACCEPT,
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        },
    )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        pass
    try:
        import email.utils

        ts = email.utils.parsedate_to_datetime(value)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)
    except (TypeError, ValueError, IndexError):
        return None


def fetch_rss(name: str, url: str, *, max_results: int = 30) -> list[EducationRecord]:
    """Fetch a university / OCW RSS or Atom feed."""
    with _client() as client:
        resp = client.get(url)
        resp.raise_for_status()
        body = resp.text
    parsed = feedparser.parse(body)
    out: list[EducationRecord] = []
    feed_title = (parsed.feed.get("title") or name or "").strip()
    for entry in (parsed.entries or [])[:max_results]:
        title = re.sub(r"\s+", " ", (entry.get("title") or "").strip())
        if not title:
            continue
        link = (entry.get("link") or "").strip()
        if link and not link.startswith("http"):
            link = urljoin(url, link)
        summary = re.sub(
            r"\s+",
            " ",
            (entry.get("summary") or entry.get("description") or "")[:2000],
        )
        authors = ""
        if entry.get("author"):
            authors = str(entry.get("author"))[:255]
        elif entry.get("authors"):
            authors = ", ".join(
                str(a.get("name") or a) for a in entry.get("authors") if a
            )[:255]
        published = None
        for key in ("published", "updated", "created"):
            if entry.get(key):
                published = _parse_date(entry.get(key))
                if published:
                    break
        ext = entry.get("id") or link or title[:48]
        tags: list[str] = []
        for t in entry.get("tags") or []:
            term = t.get("term") if isinstance(t, dict) else str(t)
            if term:
                tags.append(str(term)[:40])
        out.append(
            EducationRecord(
                title=title[:500],
                url=link or f"education://{ext}",
                summary=summary,
                authors=authors,
                published_at=published,
                source_name=name or feed_title,
                external_id=f"edu:{ext}"[:200],
                institution=name or feed_title,
                tags=tags[:8],
                raw={"title": title, "link": link},
            )
        )
    if not out:
        # 200 HTML landing pages often parse as empty feeds — surface as soft failure.
        raise ValueError(f"源无有效条目（可能已停更或返回非 RSS）：{url}")
    return out


def fetch_from_source(name: str, url: str) -> list[EducationRecord]:
    """Dispatch education source URLs (RSS / RSSHub relative)."""
    raw = (url or "").strip()
    if not raw:
        return []
    settings = get_settings()
    if raw.startswith("/"):
        base = (settings.rsshub_base_url or "").rstrip("/")
        if not base:
            raise ValueError("RSSHub 相对路径需要配置 RSSHUB_BASE_URL")
        raw = f"{base}{raw}"
    return fetch_rss(name, raw)
