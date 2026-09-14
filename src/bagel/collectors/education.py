"""Education / OCW collectors — university open learning RSS feeds + gov fallbacks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import feedparser
import httpx

from bagel.integrations.http import build_http_client
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


def fetch_rss(
    name: str,
    url: str,
    *,
    max_results: int = 30,
    force_proxy: bool | None = None,
) -> list[EducationRecord]:
    """Fetch a university / OCW RSS or Atom feed."""
    settings = get_settings()
    with build_http_client(
        settings,
        timeout=40.0,
        force_proxy=force_proxy,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": _ACCEPT,
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        },
    ) as client:
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
        raise ValueError(f"源无有效条目（可能已停更或返回非 RSS）：{url}")
    return out


def fetch_from_source(name: str, url: str) -> list[EducationRecord]:
    """Dispatch education source URLs (RSS / RSSHub / MOE / CHSI / watch)."""
    from bagel.pipeline.education_noise import filter_education_records

    return filter_education_records(_dispatch_education_source(name, url))


def _dispatch_education_source(name: str, url: str) -> list[EducationRecord]:
    from bagel.collectors.education_chsi import chsi_key_from_path, fetch_chsi_list
    from bagel.collectors.education_moe import fetch_moe_list, moe_type_from_path
    from bagel.collectors.education_watch import fetch_watch, parse_watch_ref
    from bagel.pipeline.education_tracks import parse_education_url

    parsed = parse_education_url(url)
    raw = parsed.fetch_url.strip()
    if not raw:
        return []

    # Arbitrary city/school watch subscriptions
    if parse_watch_ref(raw):
        return fetch_watch(name, raw)

    settings = get_settings()

    # Direct CHSI list pages (https://yz.chsi.com.cn/kyzx/…)
    chsi_key = chsi_key_from_path(raw)
    if chsi_key and ("yz.chsi.com.cn" in raw or raw.startswith("/chsi/") or raw.startswith("/kyzx/")):
        if raw.startswith("http") and "yz.chsi.com.cn" in raw:
            return fetch_chsi_list(name, chsi_key)
        # RSSHub /chsi/… — try hub then direct
        if raw.startswith("/"):
            base = (settings.rsshub_base_url or "").rstrip("/")
            if base:
                try:
                    return fetch_rss(name, f"{base}{raw}", force_proxy=False)
                except (httpx.HTTPError, ValueError):
                    return fetch_chsi_list(name, chsi_key)
            return fetch_chsi_list(name, chsi_key)

    if raw.startswith("/"):
        moe_type = moe_type_from_path(raw)
        base = (settings.rsshub_base_url or "").rstrip("/")
        if not base:
            if moe_type:
                return fetch_moe_list(name, moe_type)
            if chsi_key:
                return fetch_chsi_list(name, chsi_key)
            raise ValueError("RSSHub 相对路径需要配置 RSSHUB_BASE_URL")
        fetch_url = f"{base}{raw}"
        try:
            return fetch_rss(name, fetch_url, force_proxy=False)
        except (httpx.HTTPError, ValueError) as hub_exc:
            if moe_type:
                try:
                    return fetch_moe_list(name, moe_type)
                except Exception as moe_exc:  # noqa: BLE001
                    raise ValueError(
                        f"RSSHub 失败（{hub_exc}）；教育部官网直连亦失败（{moe_exc}）"
                    ) from moe_exc
            if chsi_key:
                try:
                    return fetch_chsi_list(name, chsi_key)
                except Exception as chsi_exc:  # noqa: BLE001
                    raise ValueError(
                        f"RSSHub 失败（{hub_exc}）；研招网直连亦失败（{chsi_exc}）"
                    ) from chsi_exc
            raise ValueError(
                f"RSSHub 拉取失败（{type(hub_exc).__name__}: {hub_exc}）。"
                "请检查 rsshub 容器；或改用自定义直连 RSS / 关注源。"
            ) from hub_exc

    if not raw.startswith("http"):
        raise ValueError(f"教育源需要 RSS/Atom URL、RSSHub 路径或 watch: 关注源，当前为：{raw[:80]}")

    # Absolute URL pointing at our RSSHub moe/chsi route
    base = (settings.rsshub_base_url or "").rstrip("/")
    if base and raw.startswith(base):
        path = raw[len(base) :] or "/"
        moe_type = moe_type_from_path(path)
        chsi_key2 = chsi_key_from_path(path)
        try:
            return fetch_rss(name, raw, force_proxy=False)
        except (httpx.HTTPError, ValueError) as hub_exc:
            if moe_type:
                return fetch_moe_list(name, moe_type)
            if chsi_key2:
                return fetch_chsi_list(name, chsi_key2)
            raise

    return fetch_rss(name, raw)
