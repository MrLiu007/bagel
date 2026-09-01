"""FreshRSS integration — infrastructure only, never the business source of truth."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from bagel.integrations.http import build_http_client
from bagel.settings import Settings, get_settings


@dataclass
class FreshRssStatus:
    ok: bool
    base_url: str
    message: str = ""
    status_code: int | None = None


class FreshRssClient:
    """Thin health/adapter wrapper around optional FreshRSS infra.

    Business items must live in the transactional DB (`IntelItem`). FreshRSS is
    optional RSS reading infrastructure and must not hold exclusive state.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def base_url(self) -> str:
        return self.settings.freshrss_base_url.rstrip("/")

    def ping(self, *, timeout: float = 8.0) -> FreshRssStatus:
        url = self.base_url + "/"
        try:
            with build_http_client(self.settings, timeout=timeout, force_proxy=False) as client:
                resp = client.get(url)
                return FreshRssStatus(
                    ok=resp.status_code < 500,
                    base_url=self.base_url,
                    message=f"HTTP {resp.status_code}",
                    status_code=resp.status_code,
                )
        except (httpx.HTTPError, OSError) as exc:
            return FreshRssStatus(
                ok=False,
                base_url=self.base_url,
                message=str(exc)[:300],
            )
