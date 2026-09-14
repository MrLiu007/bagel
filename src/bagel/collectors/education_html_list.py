"""Generic HTML list-page scraper for education portals."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urljoin

from bagel.collectors.education import EducationRecord, USER_AGENT
from bagel.integrations.http import build_http_client
from bagel.settings import get_settings

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Detail-like hrefs (prefer these over nav chrome).
_DETAIL_HREF = re.compile(
    r"(?:"
    r"/zsxx/Details/[a-f0-9\-]+"
    r"|/post/\d+"
    r"|/\d{4}/\d{1,2}/\d{1,2}/[a-f0-9]+\.shtml"
    r"|/docs/\d+\.pdf"
    r"|t20\d{6,}"
    r"|/\d{4}/\d{2}/t20\d+"
    r"|\.pdf(?:\?|$)"
    r"|/info/\d+/\d+\.htm"
    r"|/\w+/info/\d+"
    r")",
    re.I,
)

_NAV_NOISE = frozenset(
    {
        "首页",
        "更多",
        "登录",
        "考生登录",
        "管理人员登录",
        "返回",
        "上一页",
        "下一页",
        "尾页",
        "博士",
        "硕士",
        "港澳台",
        "联系我们",
        "网站地图",
    }
)

_DATE_NEAR = re.compile(
    r"(20\d{2})[./\-年](\d{1,2})[./\-月](\d{1,2})",
)


def fetch_html(url: str, *, referer: str | None = None) -> str:
    settings = get_settings()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    with build_http_client(
        settings,
        timeout=40.0,
        force_proxy=False,
        headers=headers,
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content.decode("utf-8", errors="replace")


def scrape_list_page(
    name: str,
    list_url: str,
    *,
    institution: str = "",
    tags: list[str] | None = None,
    max_results: int = 30,
) -> list[EducationRecord]:
    """Scrape article-like links from a university / edu-bureau list page."""
    body = fetch_html(list_url, referer=list_url.rsplit("/", 1)[0] + "/")
    items = _extract_items(body, base_url=list_url)
    out: list[EducationRecord] = []
    seen: set[str] = set()
    for href, title, date_s in items:
        link = urljoin(list_url, href)
        from bagel.pipeline.education_noise import is_education_noise

        if is_education_noise(title, link):
            continue
        if link in seen:
            continue
        seen.add(link)
        out.append(
            EducationRecord(
                title=title[:500],
                url=link,
                summary="",
                authors=institution or name,
                published_at=_parse_date(date_s),
                source_name=name,
                external_id=f"portal:{link}"[:200],
                institution=institution or name,
                tags=list(tags or [])[:8],
                raw={"list_url": list_url},
            )
        )
        if len(out) >= max_results:
            break
    return out


def _extract_items(body: str, *, base_url: str) -> list[tuple[str, str, str | None]]:
    """Return (href, title, date) preferring detail-like links."""
    found: list[tuple[str, str, str | None, int]] = []

    # Pattern A: SJTU-style card — href on <a class="item">, title in nested div.
    for m in re.finditer(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*item[^"\']*["\'][^>]*>'
        r'([\s\S]{0,800}?)</a>',
        body,
        re.I,
    ):
        href = m.group(1).strip()
        block = m.group(2)
        title_m = re.search(
            r'class=["\'][^"\']*title[^"\']*["\'][^>]*>\s*([^<]{6,120})\s*<',
            block,
            re.I,
        )
        title = _clean(title_m.group(1) if title_m else _TAG_RE.sub("", block))
        date_m = _DATE_NEAR.search(block) or _DATE_NEAR.search(body[m.end() : m.end() + 80])
        date_s = date_m.group(0) if date_m else None
        score = _score(href, title, base_url=base_url)
        if score > 0:
            found.append((href, title, date_s, score))

    # Pattern B: plain anchors (SCU / 省厅 / PKU PDF).
    for m in re.finditer(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*(?:title=["\']([^"\']*)["\'])?[^>]*>'
        r'(.*?)</a>',
        body,
        re.I | re.S,
    ):
        href = m.group(1).strip()
        title_attr = (m.group(2) or "").strip()
        inner = _clean(_TAG_RE.sub("", m.group(3) or ""))
        title = _clean(title_attr) if len(_clean(title_attr)) >= len(inner) else inner
        # PKU often embeds date in link text: "…… 2025-10-15"
        date_m = _DATE_NEAR.search(title) or _DATE_NEAR.search(body[m.end() : m.end() + 120])
        date_s = date_m.group(0) if date_m else None
        if date_m and date_m.group(0) in title:
            title = _clean(title.replace(date_m.group(0), ""))
        score = _score(href, title, base_url=base_url)
        if score > 0:
            found.append((href, title, date_s, score))

    # Dedupe by href, keep highest score.
    best: dict[str, tuple[str, str, str | None, int]] = {}
    for href, title, date_s, score in found:
        abs_h = urljoin(base_url, href)
        prev = best.get(abs_h)
        if prev is None or score > prev[3]:
            best[abs_h] = (href, title, date_s, score)

    ranked = sorted(best.values(), key=lambda x: (-x[3], x[1]))
    return [(h, t, d) for h, t, d, _s in ranked]


def _score(href: str, title: str, *, base_url: str) -> int:
    from urllib.parse import urlparse

    from bagel.pipeline.education_noise import is_education_noise

    title = _clean(title)
    abs_url = urljoin(base_url, href)
    if is_education_noise(title, abs_url):
        return 0
    if not title or len(title) < 8:
        return 0
    if title in _NAV_NOISE:
        return 0
    if not re.search(r"[\u4e00-\u9fff]{4,}", title):
        return 0
    if href in {"#", "/", "./", "javascript:;", "javascript:void(0)"}:
        return 0
    if any(x in href.lower() for x in ("login", "javascript", "void(0)")):
        return 0

    try:
        base_host = (urlparse(base_url).netloc or "").lower()
        host = (urlparse(abs_url).netloc or "").lower()
        if base_host and host and host != base_host and not abs_url.lower().endswith(".pdf"):
            return 0
    except Exception:
        pass

    score = 1
    if _DETAIL_HREF.search(href) or _DETAIL_HREF.search(abs_url):
        score += 5
    if any(k in title for k in ("招生", "简章", "通知", "公示", "复试", "调剂", "目录", "大纲", "报名")):
        score += 2
    if abs_url.lower().endswith(".pdf"):
        score += 2
    # Penalize very short nav-like paths without detail markers.
    if score < 3 and href.count("/") <= 2 and not href.lower().endswith(
        (".htm", ".html", ".shtml", ".pdf")
    ):
        return 0
    return score


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    m = _DATE_NEAR.search(value)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
    except ValueError:
        return None
