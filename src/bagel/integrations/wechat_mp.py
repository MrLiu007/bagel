"""Fetch WeChat official-account (公众号) article pages by URL.

Uses the global network/proxy settings (same as other outbound HTTP).
Does not require Gewe / ENABLE_WECHAT.

Preserves rich media in ``content`` (sanitized HTML: images, video, audio, links).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

from bagel.integrations.http import BROWSER_UA, build_http_client, fetch_text
from bagel.pipeline.textutil import strip_html, truncate
from bagel.settings import NetworkMode, Settings, get_settings

_MP_HOSTS = ("mp.weixin.qq.com",)
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_OG_TITLE_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
    re.I,
)
_OG_DESC_RE = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_OG_DESC_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
    re.I,
)
_NICK_RE = re.compile(
    r'(?:id=["\']js_name["\'][^>]*>|profile_nickname["\']?\s*>|var\s+nickname\s*=\s*["\'])'
    r"([^<\"']+)",
    re.I,
)
_NICK_META_RE = re.compile(
    r'<strong[^>]*class=["\']profile_nickname["\'][^>]*>([^<]+)</strong>',
    re.I,
)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.I)
_MSG_CTIME_RE = re.compile(r'var\s+ct\s*=\s*["\']?(\d{9,13})["\']?', re.I)
_BIZ_RE = re.compile(
    r'(?:var\s+biz\s*=\s*["\']|__biz=)([A-Za-z0-9+/=]{8,})',
    re.I,
)
_JS_CONTENT_OPEN_RE = re.compile(r'<div[^>]+id=["\']js_content["\'][^>]*>', re.I)

# Hard block pages only — WeChat HTML often contains "verify"/"captcha" in JS
# even when the article loads fine on a local IP.
_BLOCK_MARKERS = (
    "该内容无法查看",
    "此内容因违规无法查看",
    "此账号已被投诉",
    "内容已被发布者删除",
    "环境异常，完成验证后即可继续访问",
    "操作太频繁",
)

_WECHAT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36 MicroMessenger/7.0.20"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://mp.weixin.qq.com/",
    "Cache-Control": "no-cache",
}

_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "div",
        "section",
        "span",
        "strong",
        "em",
        "b",
        "i",
        "u",
        "a",
        "img",
        "video",
        "audio",
        "source",
        "iframe",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "ul",
        "ol",
        "li",
        "blockquote",
        "pre",
        "code",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "hr",
        "figure",
        "figcaption",
        "mpvoice",
        "qqmusic",
    }
)
_VOID_TAGS = frozenset({"br", "hr", "img", "source"})
_URL_ATTRS = frozenset({"href", "src", "poster", "data-src"})
_SAFE_ATTRS = frozenset(
    {
        "href",
        "src",
        "poster",
        "alt",
        "title",
        "width",
        "height",
        "controls",
        "preload",
        "type",
        "target",
        "rel",
        "class",
        "data-src",
        "data-mpid",
        "frameborder",
        "allowfullscreen",
    }
)


@dataclass(frozen=True)
class WechatMpArticle:
    url: str
    title: str
    account: str
    summary: str
    content: str  # sanitized HTML (rich media preserved)
    published_at: datetime | None
    content_is_html: bool = True
    biz: str = ""


class WechatMpError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class _RichSanitizer(HTMLParser):
    """Allowlist HTML so list/detail can render images / video / audio / links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str | None, str | None]]) -> None:
        tag_l = tag.lower()
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag_l in {"script", "style", "noscript"}:
            self._skip_depth = 1
            return
        if tag_l not in _ALLOWED_TAGS:
            return
        attr_map = {((k or "").lower()): (v or "") for k, v in attrs if k}
        # WeChat lazy images: data-src holds the real URL
        if tag_l == "img" and not attr_map.get("src") and attr_map.get("data-src"):
            attr_map["src"] = attr_map["data-src"]
        if tag_l in {"video", "audio", "source", "iframe"} and not attr_map.get("src"):
            if attr_map.get("data-src"):
                attr_map["src"] = attr_map["data-src"]
        parts = [tag_l]
        for key, val in attr_map.items():
            if key not in _SAFE_ATTRS:
                continue
            if key in _URL_ATTRS:
                low = val.strip().lower()
                if low.startswith(("javascript:", "vbscript:", "data:text/html")):
                    continue
                if key == "href" and not low.startswith(
                    ("http://", "https://", "mailto:", "/", "#", "//")
                ):
                    continue
                if key in {"src", "poster", "data-src"} and not low.startswith(
                    ("http://", "https://", "/", "//")
                ):
                    continue
            if key in {"controls", "allowfullscreen"} and val == "":
                parts.append(key)
            else:
                parts.append(f'{key}="{escape(val, quote=True)}"')
        if tag_l == "a" and "target" not in attr_map:
            parts.append('target="_blank"')
            parts.append('rel="noopener noreferrer"')
        if tag_l in _VOID_TAGS:
            self._out.append("<" + " ".join(parts) + " />")
        else:
            self._out.append("<" + " ".join(parts) + ">")

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag_l in _ALLOWED_TAGS and tag_l not in _VOID_TAGS:
            self._out.append(f"</{tag_l}>")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data:
            self._out.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        if not self._skip_depth:
            self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._skip_depth:
            self._out.append(f"&#{name};")

    def result(self) -> str:
        return "".join(self._out).strip()


def sanitize_rich_html(raw: str) -> str:
    if not (raw or "").strip():
        return ""
    parser = _RichSanitizer()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:  # noqa: BLE001
        return escape(strip_html(raw))
    return parser.result()


def is_wechat_mp_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return any(host == h or host.endswith("." + h) for h in _MP_HOSTS)


def normalize_mp_url(url: str) -> str:
    text = (url or "").strip()
    if not text:
        raise WechatMpError("请粘贴公众号文章链接")
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    if not is_wechat_mp_url(text):
        raise WechatMpError("仅支持 mp.weixin.qq.com 文章链接")
    return text.split("#", 1)[0].strip()


def _meta(html: str, primary: re.Pattern[str], alt: re.Pattern[str]) -> str:
    m = primary.search(html) or alt.search(html)
    return unescape(m.group(1)).strip() if m else ""


def _parse_published(html: str) -> datetime | None:
    m = _MSG_CTIME_RE.search(html)
    if not m:
        return None
    raw = m.group(1)
    try:
        ts = int(raw)
        if ts > 10_000_000_000:  # ms
            ts //= 1000
        return datetime.fromtimestamp(ts, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _extract_js_content(html: str) -> str:
    """Extract #js_content with nested <div> depth counting (regex is too fragile)."""
    m = _JS_CONTENT_OPEN_RE.search(html)
    if not m:
        return ""
    i = m.end()
    depth = 1
    lower = html.lower()
    n = len(html)
    while i < n and depth > 0:
        next_open = lower.find("<div", i)
        next_close = lower.find("</div", i)
        if next_close < 0:
            break
        if next_open >= 0 and next_open < next_close:
            # opening tag
            end_gt = html.find(">", next_open)
            if end_gt < 0:
                break
            depth += 1
            i = end_gt + 1
        else:
            end_gt = html.find(">", next_close)
            if end_gt < 0:
                break
            depth -= 1
            if depth == 0:
                return html[m.end() : next_close]
            i = end_gt + 1
    return html[m.end() :]


def _has_js_content(html: str) -> bool:
    return bool(_JS_CONTENT_OPEN_RE.search(html))


def _looks_blocked(html: str) -> bool:
    """Only treat as风控 when article body is missing AND hard markers appear."""
    if _has_js_content(html):
        return False
    return any(marker in html for marker in _BLOCK_MARKERS)


def parse_mp_html(html: str, *, url: str) -> WechatMpArticle:
    title = _meta(html, _OG_TITLE_RE, _OG_TITLE_RE_ALT)
    if not title:
        tm = _TITLE_TAG_RE.search(html)
        title = unescape(tm.group(1)).strip() if tm else ""
    title = re.sub(r"\s*[-_|].*微信.*$", "", title).strip() or "未命名公众号文章"

    desc = _meta(html, _OG_DESC_RE, _OG_DESC_RE_ALT)
    account = ""
    for pat in (_NICK_META_RE, _NICK_RE):
        m = pat.search(html)
        if m:
            account = unescape(m.group(1)).strip()
            if account:
                break

    body_html = _extract_js_content(html)
    rich = sanitize_rich_html(body_html) if body_html else ""
    plain = strip_html(rich) if rich else strip_html(desc)
    summary = truncate(desc or plain, 280)
    if not rich and not plain and not summary:
        raise WechatMpError("未能解析文章正文（链接可能已失效或需登录）")

    content = rich if rich else escape(plain or summary)
    biz = ""
    bm = _BIZ_RE.search(html or "")
    if bm:
        biz = bm.group(1).strip()
    return WechatMpArticle(
        url=url,
        title=title[:500],
        account=account[:255],
        summary=summary,
        content=content[:200_000],
        published_at=_parse_published(html),
        content_is_html=bool(rich),
        biz=biz[:128],
    )


def _fetch_html(
    url: str,
    *,
    settings: Settings,
    timeout: float,
    force_proxy: bool | None,
) -> str:
    with build_http_client(
        settings,
        timeout=timeout,
        force_proxy=force_proxy,
        headers=_WECHAT_HEADERS,
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def fetch_mp_article(
    url: str,
    *,
    settings: Settings | None = None,
    timeout: float = 45.0,
) -> WechatMpArticle:
    """Fetch and parse a 公众号 article. Prefer local IP; proxy only when configured mode says so."""
    s = settings or get_settings()
    clean = normalize_mp_url(url)

    force_proxy: bool | None
    if s.network_mode == NetworkMode.PROXY:
        force_proxy = True
    elif s.network_mode == NetworkMode.DIRECT:
        force_proxy = False
    else:
        force_proxy = None  # AUTO: try local first

    html = ""
    last_err: Exception | None = None
    try:
        html = _fetch_html(clean, settings=s, timeout=timeout, force_proxy=force_proxy)
    except Exception as exc:  # noqa: BLE001
        last_err = exc
        # AUTO + proxy configured: retry once via proxy
        if s.network_mode == NetworkMode.AUTO and s.proxy_url and force_proxy is not True:
            try:
                html = _fetch_html(clean, settings=s, timeout=timeout, force_proxy=True)
                last_err = None
            except Exception as exc2:  # noqa: BLE001
                last_err = exc2

    if last_err is not None and not html:
        hint = ""
        if not s.proxy_url:
            hint = "（当前为本机 IP；若持续失败可在系统设置 → 配置 → 网络 填写代理）"
        raise WechatMpError(f"拉取失败：{str(last_err)[:180]}{hint}") from last_err

    if not html or len(html) < 80:
        raise WechatMpError("页面内容过短，可能被拦截")
    if _looks_blocked(html):
        raise WechatMpError(
            "页面无法访问（内容删除/违规或需验证）。本机可访问时一般无需代理；"
            "仅当云厂商 IP 被限制时，再到系统设置 → 配置 → 网络 填写代理。"
        )
    return parse_mp_html(html, url=clean)


# Keep fetch_text import used by tests / callers that monkeypatch http layer.
_ = (fetch_text, BROWSER_UA)

__all__ = [
    "WechatMpArticle",
    "WechatMpError",
    "fetch_mp_article",
    "is_wechat_mp_url",
    "normalize_mp_url",
    "parse_mp_html",
    "sanitize_rich_html",
]
