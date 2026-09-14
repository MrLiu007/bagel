"""Optional WeWe-RSS client — recent 公众号 articles via 微信读书-backed feeds.

Infrastructure dependency only (like FreshRSS/RSSHub). Does not fork WeWe-RSS.
Configure ``WEWE_RSS_BASE_URL`` (e.g. ``http://127.0.0.1:4000``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from bagel.integrations.http import build_http_client
from bagel.settings import Settings, get_settings


@dataclass(frozen=True)
class WeweFeedInfo:
    id: str
    name: str
    intro: str = ""


class WeweRssClient:
    """Read WeWe-RSS feed list / JSON feed. Internal service — no egress proxy."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def base_url(self) -> str:
        configured = (getattr(self.settings, "wewe_rss_base_url", None) or "").rstrip("/")
        if configured:
            return configured
        try:
            from bagel.services.wewe_runtime import effective_wewe_base_url

            return effective_wewe_base_url(self.settings).rstrip("/")
        except Exception:  # noqa: BLE001
            return ""

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json, text/html, */*"}
        code = (getattr(self.settings, "wewe_rss_auth_code", None) or "").strip()
        if not code:
            code = "bagel-wewe"
        if code:
            headers["Authorization"] = code
        return headers

    def _get(self, path: str, *, timeout: float = 20.0) -> httpx.Response:
        if not self.base_url:
            raise RuntimeError("WEWE_RSS_BASE_URL 未配置")
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        with build_http_client(
            self.settings, timeout=timeout, force_proxy=False, headers=self._headers()
        ) as client:
            return client.get(url)

    def list_feeds(self, *, timeout: float = 15.0) -> list[WeweFeedInfo]:
        try:
            resp = self._get("/feeds", timeout=timeout)
            if resp.status_code >= 400:
                return []
            raw = resp.json()
        except (httpx.HTTPError, OSError, ValueError, TypeError):
            return []
        if not isinstance(raw, list):
            return []
        out: list[WeweFeedInfo] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            fid = str(row.get("id") or "").strip()
            name = str(row.get("name") or "").strip()
            if not fid or not name:
                continue
            out.append(
                WeweFeedInfo(
                    id=fid,
                    name=name,
                    intro=str(row.get("intro") or "")[:200],
                )
            )
        return out

    def match_feed(
        self,
        *,
        name: str = "",
        feed_id: str = "",
    ) -> WeweFeedInfo | None:
        feeds = self.list_feeds()
        if not feeds:
            return None
        fid = (feed_id or "").strip()
        if fid:
            for f in feeds:
                if f.id == fid:
                    return f
        needle = (name or "").strip().lower().replace(" ", "")
        if not needle:
            return None
        exact = [f for f in feeds if f.name.strip().lower().replace(" ", "") == needle]
        if exact:
            return exact[0]
        soft = [
            f
            for f in feeds
            if needle in f.name.strip().lower().replace(" ", "")
            or f.name.strip().lower().replace(" ", "") in needle
        ]
        return soft[0] if len(soft) == 1 else (soft[0] if soft else None)

    def feed_json_url(self, feed_id: str, *, limit: int = 10) -> str:
        fid = quote((feed_id or "").strip(), safe="")
        lim = max(1, min(50, int(limit)))
        return f"{self.base_url}/feeds/{fid}.json?limit={lim}"

    def fetch_feed_body(self, feed_id: str, *, limit: int = 10, timeout: float = 25.0) -> str:
        path = f"/feeds/{quote((feed_id or '').strip(), safe='')}.json?limit={max(1, min(50, int(limit)))}"
        resp = self._get(path, timeout=timeout)
        resp.raise_for_status()
        return resp.text or ""

    def ping(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "未配置 WEWE_RSS_BASE_URL / sidecar 未启动"}
        try:
            feeds = self.list_feeds()
            return {"ok": True, "feeds": len(feeds), "base": self.base_url}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:200], "base": self.base_url}
