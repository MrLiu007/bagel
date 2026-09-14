"""Discover WeChat OA article URLs by account name / 微信号 / feed.

Priority (recent articles):
1. Explicit ``feed:`` URL on the IntelSource (WeWe-RSS / Atom / RSS / JSON Feed)
2. WeWe-RSS match by name when ``WEWE_RSS_BASE_URL`` is configured
3. Optional Sogou keyword search (sparse/outdated — off by default)

Sogou is kept only as a degraded fallback; prefer WeWe-RSS or a pasted feed URL.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import unescape
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

import feedparser
import httpx

from bagel.integrations.http import BROWSER_UA, build_http_client
from bagel.integrations.wewe_rss import WeweRssClient
from bagel.settings import NetworkMode, Settings, get_settings

_SCHEME_PREFIX = "wechat:mp:"
_NAME_PART_RE = re.compile(r"(?:^|[|])name:([^|]+)", re.I)
_WXID_PART_RE = re.compile(r"(?:^|[|])wxid:([^|]+)", re.I)
_BIZ_PART_RE = re.compile(r"(?:^|[|])biz:([^|]+)", re.I)
_FEED_PART_RE = re.compile(r"(?:^|[|])feed:(https?://[^|]+)", re.I)
_SOGOU_HOST = "https://weixin.sogou.com"
_SOGOU_LINK_RE = re.compile(
    r'''href=["']((?:https?://weixin\.sogou\.com)?/link\?[^"']+)["']''',
    re.I,
)
_MP_HREF_RE = re.compile(
    r'href=["\'](https?://mp\.weixin\.qq\.com/s[^"\']+)["\']',
    re.I,
)
_WXID_LABEL_RE = re.compile(r"微信号\s*[:：]\s*([A-Za-z0-9_\-.]{2,64})", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_LI_RE = re.compile(r'<li[^>]*id="sogou_vr_[^"]+"[^>]*>([\s\S]*?)</li>', re.I)
_TITLE_A_RE = re.compile(
    r'<h3>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
    re.I,
)
_AUTHOR_RE = re.compile(r'class="all-time-y2"[^>]*>([\s\S]*?)</span>', re.I)
_URL_PLUS_RE = re.compile(r"url\s*\+=\s*'([^']*)'")
_ANTISPIDER_MARKERS = ("antispider", "请输入验证", "验证码", "访问过于频繁")
_MP_LINK_RE = re.compile(r"https?://mp\.weixin\.qq\.com/s[^\s\"'<>]+", re.I)


@dataclass(frozen=True)
class WechatMpSourceRef:
    """Parsed ``wechat:mp:…`` IntelSource.url."""

    name: str
    wxid: str = ""
    biz: str = ""
    feed_url: str = ""

    @property
    def label(self) -> str:
        return self.name or self.wxid or self.biz or "未命名公众号"


@dataclass(frozen=True)
class DiscoveredArticle:
    url: str
    title: str = ""
    author: str = ""
    published_at: datetime | None = None


def build_source_url(
    *,
    name: str = "",
    wxid: str = "",
    biz: str = "",
    feed_url: str = "",
) -> str:
    parts: list[str] = []
    n = (name or "").strip()
    w = (wxid or "").strip()
    b = (biz or "").strip()
    f = (feed_url or "").strip()
    if n:
        parts.append(f"name:{n}")
    if w:
        parts.append(f"wxid:{w}")
    if b:
        parts.append(f"biz:{b}")
    if f:
        if not f.startswith(("http://", "https://")):
            raise ValueError("RSS 源地址须以 http:// 或 https:// 开头")
        parts.append(f"feed:{f}")
    if not parts:
        raise ValueError("名称、微信号、RSS 源至少填一项")
    return _SCHEME_PREFIX + "|".join(parts)


def parse_source_url(url: str) -> WechatMpSourceRef:
    text = (url or "").strip()
    if not text.lower().startswith(_SCHEME_PREFIX):
        return WechatMpSourceRef(name=text, wxid="")
    body = text[len(_SCHEME_PREFIX) :]
    name_m = _NAME_PART_RE.search(body)
    wxid_m = _WXID_PART_RE.search(body)
    biz_m = _BIZ_PART_RE.search(body)
    feed_m = _FEED_PART_RE.search(body)
    name = unquote(name_m.group(1)).strip() if name_m else ""
    wxid = unquote(wxid_m.group(1)).strip() if wxid_m else ""
    biz = unquote(biz_m.group(1)).strip() if biz_m else ""
    feed_url = unquote(feed_m.group(1)).strip() if feed_m else ""
    if not name and not wxid and not biz and not feed_url:
        name = unquote(body).strip()
    return WechatMpSourceRef(name=name, wxid=wxid, biz=biz, feed_url=feed_url)


def _strip_tags(raw: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", unescape(raw or ""))).strip()


def _browser_headers(*, referer: str | None = None) -> dict[str, str]:
    return {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer or f"{_SOGOU_HOST}/",
    }


def _force_proxy(settings: Settings) -> bool | None:
    if settings.network_mode == NetworkMode.PROXY:
        return True
    if settings.network_mode == NetworkMode.DIRECT:
        return False
    return None


def _looks_antispider(html: str) -> bool:
    low = (html or "").lower()
    return any(m.lower() in low or m in (html or "") for m in _ANTISPIDER_MARKERS)


def _normalize_account(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", "", t)
    return t.replace("&amp;", "&")


def _author_matches(subscribed: str, author: str) -> bool:
    a = _normalize_account(author)
    s = _normalize_account(subscribed)
    if not a or not s:
        return False
    if a == s:
        return True
    if len(s) >= 2 and (s in a or a in s):
        return True
    return False


def _absolute_sogou_link(href: str) -> str:
    h = unescape((href or "").strip())
    if not h:
        return ""
    if h.startswith("//"):
        return "https:" + h
    return urljoin(_SOGOU_HOST + "/", h)


def _extract_mp_from_bridge_html(html: str) -> str:
    parts = _URL_PLUS_RE.findall(html or "")
    if parts:
        url = "".join(parts).replace("@", "")
        if "mp.weixin.qq.com" in url:
            return url.split("#", 1)[0]
    for m in _MP_HREF_RE.finditer(html or ""):
        return m.group(1).split("#", 1)[0]
    m = re.search(
        r"window\.location\.replace\(\s*['\"](https?://mp\.weixin\.qq\.com/[^'\"]+)['\"]",
        html or "",
        re.I,
    )
    if m:
        return m.group(1).split("#", 1)[0]
    return ""


def _parse_sogou_article_items(html: str) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for li in _LI_RE.finditer(html or ""):
        chunk = li.group(1)
        a = _TITLE_A_RE.search(chunk)
        if not a:
            m = re.search(
                r'class="txt-box"[\s\S]*?href=["\']((?:https?://weixin\.sogou\.com)?/link\?[^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                chunk,
                re.I,
            )
            if not m:
                continue
            href, title_html = m.group(1), m.group(2)
        else:
            href, title_html = a.group(1), a.group(2)
        title = _strip_tags(title_html)
        author = ""
        am = _AUTHOR_RE.search(chunk)
        if am:
            author = _strip_tags(am.group(1))
        out.append((href, title, author))
    if out:
        return out
    for m in _SOGOU_LINK_RE.finditer(html or ""):
        out.append((m.group(1), "", ""))
        if len(out) >= 20:
            break
    return out


def _parse_feed_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    # feedparser struct_time via published_parsed handled by caller
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            cleaned = text.replace("Z", "+0000") if fmt.endswith("%z") else text
            if fmt.endswith("%z") and cleaned.endswith("Z"):
                cleaned = cleaned[:-1] + "+0000"
            dt = datetime.strptime(cleaned[:26].replace("+0000", "+0000"), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        # ISO loosely
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_feed_articles(body: str, *, limit: int = 10) -> list[DiscoveredArticle]:
    """Parse RSS / Atom / JSON Feed body into mp.weixin article links."""
    text = (body or "").strip()
    if not text:
        return []
    out: list[DiscoveredArticle] = []
    seen: set[str] = set()

    def _add(url: str, title: str = "", author: str = "", published: datetime | None = None) -> None:
        u = (url or "").strip().split("#", 1)[0]
        if "mp.weixin.qq.com" not in u or u in seen:
            return
        seen.add(u)
        out.append(DiscoveredArticle(url=u, title=_strip_tags(title), author=author, published_at=published))

    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            items = data.get("items") or data.get("entries") or []
            feed_title = str(data.get("title") or "")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    link = (
                        item.get("url")
                        or item.get("external_url")
                        or item.get("id")
                        or ""
                    )
                    if isinstance(link, dict):
                        link = link.get("href") or ""
                    title = str(item.get("title") or "")
                    authors = item.get("authors") or item.get("author")
                    author = ""
                    if isinstance(authors, list) and authors:
                        a0 = authors[0]
                        author = str(a0.get("name") if isinstance(a0, dict) else a0)
                    elif isinstance(authors, dict):
                        author = str(authors.get("name") or "")
                    elif isinstance(authors, str):
                        author = authors
                    if not author:
                        author = feed_title
                    pub = _parse_feed_datetime(
                        item.get("date_published")
                        or item.get("date_modified")
                        or item.get("published")
                    )
                    _add(str(link), title, author, pub)
                    if len(out) >= limit:
                        return out
        return out[:limit]

    parsed = feedparser.parse(text)
    feed_title = _strip_tags(getattr(parsed.feed, "title", "") or "")
    for entry in parsed.entries[: limit * 2]:
        link = (getattr(entry, "link", None) or "").strip()
        title = _strip_tags(getattr(entry, "title", None) or "")
        author = _strip_tags(getattr(entry, "author", None) or "") or feed_title
        published = None
        pp = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if pp:
            try:
                published = datetime(*pp[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                published = None
        if not published:
            published = _parse_feed_datetime(getattr(entry, "published", None))
        _add(link, title, author, published)
        if len(out) >= limit:
            break
    # last resort: raw mp links in body
    if not out:
        for m in _MP_LINK_RE.finditer(text):
            _add(m.group(0))
            if len(out) >= limit:
                break
    return out[:limit]


def _within_lookback(art: DiscoveredArticle, *, lookback_days: int) -> bool:
    if lookback_days <= 0 or art.published_at is None:
        return True
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    pub = art.published_at
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=UTC)
    return pub >= cutoff


def _fetch_http_text(url: str, *, settings: Settings, timeout: float = 25.0) -> str:
    """Fetch feed URL; prefer direct for localhost / internal hosts."""
    host = (urlparse(url).hostname or "").lower()
    internal = host in {"localhost", "127.0.0.1", "rsshub", "freshrss", "wewe-rss"} or host.endswith(
        ".local"
    )
    force: bool | None = False if internal else _force_proxy(settings)
    try:
        with build_http_client(
            settings, timeout=timeout, force_proxy=force, headers=_browser_headers()
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text or ""
    except Exception:
        if (
            not internal
            and settings.network_mode == NetworkMode.AUTO
            and settings.proxy_url
            and force is not True
        ):
            with build_http_client(
                settings, timeout=timeout, force_proxy=True, headers=_browser_headers()
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text or ""
        raise


def _discover_via_feed_url(
    feed_url: str,
    *,
    settings: Settings,
    limit: int,
    lookback_days: int,
) -> tuple[list[DiscoveredArticle], dict[str, Any]]:
    meta: dict[str, Any] = {"feed_url": feed_url}
    try:
        body = _fetch_http_text(feed_url, settings=settings)
    except Exception as exc:  # noqa: BLE001
        meta["error"] = str(exc)[:160]
        return [], meta
    arts = parse_feed_articles(body, limit=max(limit, limit * 2))
    meta["raw"] = len(arts)
    filtered = [a for a in arts if _within_lookback(a, lookback_days=lookback_days)]
    # If lookback wiped everything (feed only has old dates / missing dates), keep raw head
    if not filtered and arts:
        filtered = arts[:limit]
        meta["lookback_relaxed"] = True
    meta["kept"] = len(filtered[:limit])
    return filtered[:limit], meta


def _discover_via_wewe(
    ref: WechatMpSourceRef,
    *,
    settings: Settings,
    limit: int,
    lookback_days: int,
) -> tuple[list[DiscoveredArticle], dict[str, Any]]:
    meta: dict[str, Any] = {}
    client = WeweRssClient(settings)
    if not client.enabled:
        meta["skipped"] = "not_configured"
        return [], meta
    matched = client.match_feed(name=ref.name)
    if not matched:
        meta["error"] = "WeWe-RSS 中未找到同名公众号，请先在 WeWe 用样例文章链接添加该号"
        meta["feeds"] = len(client.list_feeds())
        return [], meta
    meta["feed_id"] = matched.id
    meta["feed_name"] = matched.name
    try:
        body = client.fetch_feed_body(matched.id, limit=max(limit, 12))
    except Exception as exc:  # noqa: BLE001
        meta["error"] = str(exc)[:160]
        return [], meta
    arts = parse_feed_articles(body, limit=max(limit, limit * 2))
    for i, a in enumerate(list(arts)):
        if not a.author:
            arts[i] = DiscoveredArticle(
                url=a.url, title=a.title, author=matched.name, published_at=a.published_at
            )
    filtered = [a for a in arts if _within_lookback(a, lookback_days=lookback_days)]
    if not filtered and arts:
        filtered = arts[:limit]
        meta["lookback_relaxed"] = True
    meta["kept"] = len(filtered[:limit])
    return filtered[:limit], meta


class _SogouSession:
    def __init__(self, settings: Settings, *, force_proxy: bool | None) -> None:
        self.settings = settings
        self.client = build_http_client(
            settings,
            timeout=25.0,
            force_proxy=force_proxy,
            headers=_browser_headers(),
        )
        self._warmed = False
        self.last_search_url = ""
        self.antispider = False

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> _SogouSession:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def warm(self) -> None:
        if self._warmed:
            return
        try:
            self.client.get(_SOGOU_HOST + "/", headers=_browser_headers())
        except Exception:  # noqa: BLE001
            pass
        self._warmed = True

    def get_html(self, url: str, *, referer: str | None = None) -> str:
        self.warm()
        resp = self.client.get(url, headers=_browser_headers(referer=referer))
        resp.raise_for_status()
        text = resp.text or ""
        if _looks_antispider(text):
            self.antispider = True
        return text

    def resolve_mp_url(self, href: str) -> str:
        full = _absolute_sogou_link(href)
        if not full:
            return ""
        if "mp.weixin.qq.com/s" in full:
            return full.split("#", 1)[0]
        referer = self.last_search_url or (_SOGOU_HOST + "/")
        try:
            resp = self.client.get(
                full,
                headers=_browser_headers(referer=referer),
                follow_redirects=False,
            )
        except Exception:  # noqa: BLE001
            return ""
        loc = (resp.headers.get("location") or "").strip()
        if loc:
            loc = urljoin(full, loc)
            if "mp.weixin.qq.com/s" in loc:
                return loc.split("#", 1)[0]
        body = resp.text or ""
        if _looks_antispider(body):
            self.antispider = True
            return ""
        return _extract_mp_from_bridge_html(body)


def _open_sogou(settings: Settings) -> _SogouSession:
    force = _force_proxy(settings)
    try:
        return _SogouSession(settings, force_proxy=force)
    except Exception:
        if settings.network_mode == NetworkMode.AUTO and settings.proxy_url and force is not True:
            return _SogouSession(settings, force_proxy=True)
        raise


def resolve_wxid_from_name(
    name: str,
    *,
    settings: Settings | None = None,
    timeout: float = 25.0,
) -> str:
    del timeout
    s = settings or get_settings()
    q = (name or "").strip()
    if not q:
        return ""
    url = f"{_SOGOU_HOST}/weixin?type=1&query={quote(q)}&ie=utf8"
    try:
        with _open_sogou(s) as sess:
            html = sess.get_html(url)
    except Exception:  # noqa: BLE001
        return ""
    m = _WXID_LABEL_RE.search(html or "")
    return m.group(1).strip() if m else ""


def _discover_via_sogou_articles(
    name: str,
    *,
    settings: Settings,
    limit: int,
) -> tuple[list[DiscoveredArticle], dict[str, Any]]:
    q = (name or "").strip()
    meta: dict[str, Any] = {
        "sogou_hits": 0,
        "author_matched": 0,
        "antispider": False,
        "empty_page": False,
    }
    if not q:
        return [], meta

    search = (
        f"{_SOGOU_HOST}/weixin?type=2&query={quote(q)}&ie=utf8&_sug_=n&_sug_type_="
    )
    try:
        with _open_sogou(settings) as sess:
            html = sess.get_html(search)
            sess.last_search_url = search
            meta["antispider"] = sess.antispider
            if "noresult_part1_container" in html or "b404-box" in html:
                meta["empty_page"] = True
                return [], meta

            items = _parse_sogou_article_items(html)
            meta["sogou_hits"] = len(items)
            matched = [it for it in items if _author_matches(q, it[2])]
            exact = [
                it
                for it in matched
                if _normalize_account(it[2]) == _normalize_account(q)
            ]
            chosen = exact or matched
            meta["author_matched"] = len(chosen)
            if not chosen:
                meta["other_authors"] = sorted({a for _, _, a in items if a})[:12]
                return [], meta

            out: list[DiscoveredArticle] = []
            seen: set[str] = set()
            for href, title, author in chosen:
                if len(out) >= limit:
                    break
                mp = sess.resolve_mp_url(href)
                if not mp or mp in seen:
                    continue
                seen.add(mp)
                out.append(DiscoveredArticle(url=mp, title=title, author=author))
            meta["antispider"] = meta["antispider"] or sess.antispider
            meta["resolved"] = len(out)
            return out, meta
    except (httpx.HTTPError, OSError) as exc:
        meta["error"] = str(exc)[:160]
        return [], meta


def discover_articles(
    ref: WechatMpSourceRef,
    *,
    settings: Settings | None = None,
    limit: int = 8,
) -> tuple[list[DiscoveredArticle], dict[str, Any]]:
    """Return recent article URLs for a subscribed account."""
    s = settings or get_settings()
    limit = max(1, min(20, int(limit)))
    lookback = int(getattr(s, "collect_lookback_days", 14) or 14)
    meta: dict[str, Any] = {
        "methods": [],
        "wxid": ref.wxid,
        "name": ref.name,
        "biz": ref.biz,
        "feed_url": ref.feed_url,
    }
    articles: list[DiscoveredArticle] = []
    seen: set[str] = set()

    def _merge(batch: list[DiscoveredArticle], method: str) -> None:
        if not batch:
            return
        meta["methods"].append(method)
        for a in batch:
            if a.url not in seen:
                seen.add(a.url)
                articles.append(a)

    # 1) Explicit feed URL
    if ref.feed_url and len(articles) < limit:
        feed_arts, feed_meta = _discover_via_feed_url(
            ref.feed_url, settings=s, limit=limit, lookback_days=lookback
        )
        meta["feed"] = feed_meta
        _merge(feed_arts, "feed")

    # 2) WeWe-RSS by name
    if len(articles) < limit and ref.name:
        wewe_arts, wewe_meta = _discover_via_wewe(
            ref, settings=s, limit=limit - len(articles), lookback_days=lookback
        )
        meta["wewe"] = wewe_meta
        _merge(wewe_arts, "wewe")

    # 3) Optional Sogou (default off — index is sparse / stale)
    enable_sogou = bool(getattr(s, "wechat_mp_enable_sogou", False))
    if enable_sogou and len(articles) < limit and (ref.name or ref.wxid):
        sogou, sogou_meta = _discover_via_sogou_articles(
            ref.name or ref.wxid, settings=s, limit=limit - len(articles)
        )
        meta["sogou"] = sogou_meta
        _merge(sogou, "sogou")

    meta["found"] = len(articles)
    meta["sogou_enabled"] = enable_sogou
    return articles[:limit], meta


def empty_discover_hint(name: str, meta: dict[str, Any]) -> str:
    """User-facing reason when discovery returns no articles."""
    feed = meta.get("feed") if isinstance(meta.get("feed"), dict) else {}
    wewe = meta.get("wewe") if isinstance(meta.get("wewe"), dict) else {}
    sogou = meta.get("sogou") if isinstance(meta.get("sogou"), dict) else {}

    if feed.get("error"):
        return f"{name}: RSS 源拉取失败（{feed.get('error')}）"
    if wewe.get("error"):
        return f"{name}: {wewe.get('error')}"
    if sogou.get("antispider"):
        return f"{name}: 搜狗风控/验证码，稍后重试或配置代理"
    if sogou.get("sogou_hits", 0) > 0 and sogou.get("author_matched", 0) == 0:
        others = sogou.get("other_authors") or []
        extra = f"（搜到其他号：{'、'.join(others[:4])}）" if others else ""
        return f"{name}: 搜狗未找到该号自己的文章{extra}"
    if not meta.get("sogou_enabled"):
        return (
            f"{name}: 未发现近期文章。请配置 WeWe-RSS（推荐），"
            "或在订阅时填写该号的 RSS 源地址 / 样例文章链接绑定 feed"
        )
    if sogou.get("empty_page"):
        return f"{name}: 搜狗无结果，请核对公众号名称"
    if sogou.get("error"):
        return f"{name}: 搜狗请求失败（{sogou.get('error')}）"
    return f"{name}: 未发现文章"
