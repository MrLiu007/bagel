"""RSSHub client — adapter for sites without native RSS."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from bagel.integrations.http import build_http_client
from bagel.settings import Settings, get_settings


@dataclass
class RsshubFeed:
    path: str
    url: str
    ok: bool
    status_code: int | None = None
    error: str | None = None
    body: str | None = None


class RsshubClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def feed_url(self, path: str) -> str:
        base = self.settings.rsshub_base_url.rstrip("/")
        path = path if path.startswith("/") else f"/{path}"
        return f"{base}{path}"

    def fetch_feed(self, path: str, *, timeout: float = 20.0) -> RsshubFeed:
        url = self.feed_url(path)
        try:
            # Internal service — never go through external proxy.
            with build_http_client(self.settings, timeout=timeout, force_proxy=False) as client:
                resp = client.get(url)
                if resp.status_code >= 400:
                    return RsshubFeed(
                        path=path,
                        url=url,
                        ok=False,
                        status_code=resp.status_code,
                        error=f"HTTP {resp.status_code}",
                    )
                return RsshubFeed(
                    path=path,
                    url=url,
                    ok=True,
                    status_code=resp.status_code,
                    body=resp.text,
                )
        except (httpx.HTTPError, OSError) as exc:
            return RsshubFeed(path=path, url=url, ok=False, error=str(exc)[:300])

    def ping(self) -> bool:
        result = self.fetch_feed("/", timeout=5.0)
        # RSSHub root may 200 or redirect; connection success is enough.
        return result.ok or result.status_code is not None
