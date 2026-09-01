"""HTTP client helpers with network-mode / proxy awareness."""

from __future__ import annotations

import httpx

from bagel.settings import NetworkMode, Settings, get_settings

DEFAULT_UA = "AI-bagel/0.3 (+https://github.com/local/ai-bagel)"
# Reddit rejects bot-shaped Accept / UA; use browser-navigation headers.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
REDDIT_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def _is_reddit_url(url: str) -> bool:
    low = (url or "").lower()
    return "reddit.com" in low or "redd.it" in low


def request_headers_for_url(url: str) -> dict[str, str]:
    if _is_reddit_url(url):
        return dict(REDDIT_HEADERS)
    return {"User-Agent": DEFAULT_UA}


def build_http_client(
    settings: Settings | None = None,
    *,
    timeout: float = 30.0,
    force_proxy: bool | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Client:
    s = settings or get_settings()
    proxies: str | None = None

    use_proxy = False
    if force_proxy is True:
        use_proxy = True
    elif force_proxy is False:
        use_proxy = False
    elif s.network_mode == NetworkMode.PROXY:
        use_proxy = True
    elif s.network_mode == NetworkMode.DIRECT:
        use_proxy = False
    # AUTO: caller may retry with force_proxy=True

    if use_proxy:
        proxies = s.proxy_url

    return httpx.Client(
        timeout=timeout,
        proxy=proxies,
        follow_redirects=True,
        headers=headers or {"User-Agent": DEFAULT_UA},
    )


def fetch_text(
    url: str,
    *,
    settings: Settings | None = None,
    timeout: float = 30.0,
    prefer_proxy: bool = False,
) -> tuple[str, int, dict[str, str]]:
    """Fetch URL text. On AUTO+failure with proxy configured, retry via proxy once."""
    s = settings or get_settings()
    hdrs = request_headers_for_url(url)
    try:
        with build_http_client(
            s, timeout=timeout, force_proxy=prefer_proxy or None, headers=hdrs
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.text, resp.status_code, headers
    except (httpx.HTTPError, OSError):
        if (
            s.network_mode == NetworkMode.AUTO
            and s.proxy_url
            and not prefer_proxy
        ):
            with build_http_client(s, timeout=timeout, force_proxy=True, headers=hdrs) as client:
                resp = client.get(url)
                resp.raise_for_status()
                headers = {k.lower(): v for k, v in resp.headers.items()}
                return resp.text, resp.status_code, headers
        raise
