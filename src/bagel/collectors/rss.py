"""RSS / RSSHub feed collector.

Collectors only fetch + normalize into `NormalizedItem`. Persistence, keyword
filtering, and category assignment belong in jobs / pipeline layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import feedparser

from bagel import __version__
from bagel.domain.enums import ErrorCode, ItemType, SourceType
from bagel.domain.models import IntelSource
from bagel.integrations.http import fetch_text
from bagel.pipeline.normalize import from_rss_entry
from bagel.domain.contracts import NormalizedItem
from bagel.settings import Settings, get_settings


@dataclass
class CollectResult:
    """Outcome of one feed fetch (items may be empty when ``error_code`` is set)."""

    items: list[NormalizedItem] = field(default_factory=list)
    raw_entries: list[dict[str, Any]] = field(default_factory=list)
    http_status: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error_code is None


class RssCollector:
    """Fetch one `IntelSource` feed and emit normalized news/stock items."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def resolve_feed_url(self, source: IntelSource) -> str:
        """Expand RSSHub-relative paths against ``RSSHUB_BASE_URL``."""
        url = source.url
        # STOCK feeds may also store RSSHub-relative paths.
        needs_hub = source.source_type in {SourceType.RSSHUB, SourceType.STOCK}
        if needs_hub and not url.startswith("http"):
            base = self.settings.rsshub_base_url.rstrip("/")
            path = url if url.startswith("/") else f"/{url}"
            return f"{base}{path}"
        if source.source_type == SourceType.RSSHUB and "rsshub" not in url:
            # Relative path stored as /route
            if url.startswith("/"):
                return f"{self.settings.rsshub_base_url.rstrip('/')}{url}"
        return url

    def collect_source(self, source: IntelSource) -> CollectResult:
        feed_url = self.resolve_feed_url(source)
        prefer_proxy = source.network_requirement == "PROXY_PREFERRED"
        try:
            text, status, headers = fetch_text(
                feed_url,
                settings=self.settings,
                prefer_proxy=prefer_proxy,
            )
        except Exception as exc:  # noqa: BLE001 — classify for job status
            code = _classify_network_error(exc)
            return CollectResult(error_code=code, error_message=str(exc)[:500])

        parsed = feedparser.parse(text)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            return CollectResult(
                http_status=status,
                headers=headers,
                error_code=ErrorCode.PARSE_ERROR,
                error_message=str(getattr(parsed, "bozo_exception", "parse error"))[:500],
            )

        items: list[NormalizedItem] = []
        raw_entries: list[dict[str, Any]] = []
        for entry in parsed.entries:
            # Convert feedparser entry to plain dict-ish
            entry_dict = {k: entry.get(k) for k in entry.keys()}
            # struct_time is not JSON-serializable — stringify in raw later
            raw_safe = _json_safe_entry(entry_dict)
            raw_entries.append(raw_safe)
            item_type = (
                ItemType.STOCK_NEWS
                if source.source_type == SourceType.STOCK
                else ItemType.NEWS
            )
            normalized = from_rss_entry(
                entry_dict,
                source_id=source.id,
                source_type=source.source_type,
                feed_url=feed_url,
                item_type=item_type,
            )
            if normalized:
                normalized.http_status = status
                normalized.etag = headers.get("etag")
                normalized.last_modified = headers.get("last-modified")
                normalized.raw_payload = raw_safe
                items.append(normalized)

        return CollectResult(
            items=items,
            raw_entries=raw_entries,
            http_status=status,
            headers=headers,
        )


def _json_safe_entry(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in entry.items():
        if k.endswith("_parsed"):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, list):
            out[k] = [
                {kk: vv for kk, vv in item.items() if isinstance(vv, (str, int, float, bool, type(None)))}
                if isinstance(item, dict)
                else str(item)
                for item in v
            ]
        elif isinstance(v, dict):
            out[k] = {
                kk: vv
                for kk, vv in v.items()
                if isinstance(vv, (str, int, float, bool, type(None)))
            }
        else:
            out[k] = str(v)
    return out


def _classify_network_error(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timeout" in msg:
        return ErrorCode.NETWORK_TIMEOUT
    if "connect" in name or "unreachable" in msg or "name or service" in msg:
        return ErrorCode.NETWORK_UNREACHABLE
    if "401" in msg or "403" in msg:
        return ErrorCode.AUTH_FAILED
    if "429" in msg:
        return ErrorCode.RATE_LIMITED
    if "http" in name:
        return ErrorCode.HTTP_ERROR
    return ErrorCode.NETWORK_UNREACHABLE


COLLECTOR_VERSION = __version__
