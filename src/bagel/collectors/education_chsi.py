"""Direct HTML fetch for 研招网 (yz.chsi.com.cn) — RSSHub-independent."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urljoin

from bagel.collectors.education import EducationRecord, USER_AGENT
from bagel.integrations.http import build_http_client
from bagel.settings import get_settings

CHSI_HOST = "https://yz.chsi.com.cn"

# path key → (list_url, label, facet)
CHSI_LIST_PAGES: dict[str, tuple[str, str, str]] = {
    "zcdh": (f"{CHSI_HOST}/kyzx/zcdh/", "研招网 · 政策导航", "national"),
    "kydt": (f"{CHSI_HOST}/kyzx/kydt/", "研招网 · 考研动态", "national"),
    "fstj": (f"{CHSI_HOST}/kyzx/fstj/", "研招网 · 复试调剂", "score"),
    "hotnews": (f"{CHSI_HOST}/kyzx/kydt/", "研招网 · 热点/动态", "national"),
}

_TAG_RE = re.compile(r"<[^>]+>")
# Prefer news-list style; fallback to generic dated links under /kyzx/
_ITEM_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']*kyzx[^"\']+\.html?)["\'][^>]*>(.*?)</a>'
    r'(?:[\s\S]{0,120}?([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{4}/[0-9]{2}/[0-9]{2}))?',
    re.I,
)


def chsi_key_from_path(path: str) -> str | None:
    raw = (path or "").strip()
    full = raw.lower()
    if "://" in raw:
        from urllib.parse import urlparse

        raw = urlparse(raw).path or ""
    raw = raw.rstrip("/").lower()
    # /chsi/kyzx/zcdh  or  /kyzx/zcdh
    m = re.search(r"(?:/chsi)?/kyzx/([a-z]+)$", raw)
    if m:
        key = m.group(1)
        return key if key in CHSI_LIST_PAGES else None
    # Legacy RSSHub shortcuts: /chsi/kydt /chsi/hotnews
    m_short = re.search(r"/chsi/(zcdh|kydt|fstj|hotnews)$", raw)
    if m_short:
        key = m_short.group(1)
        return "kydt" if key == "hotnews" else key
    # absolute https://yz.chsi.com.cn/kyzx/zcdh/
    m2 = re.search(r"yz\.chsi\.com\.cn/kyzx/([a-z]+)", full)
    if m2:
        key = m2.group(1)
        return key if key in CHSI_LIST_PAGES else None
    return None


def fetch_chsi_list(
    name: str,
    key: str,
    *,
    max_results: int = 30,
    title_filter: str | None = None,
) -> list[EducationRecord]:
    page = CHSI_LIST_PAGES.get(key)
    if not page:
        raise ValueError(f"未知研招网栏目：{key}")
    list_url, default_name, _facet = page
    settings = get_settings()
    with build_http_client(
        settings,
        timeout=40.0,
        force_proxy=False,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": CHSI_HOST + "/",
        },
    ) as client:
        resp = client.get(list_url)
        resp.raise_for_status()
        body = resp.content.decode("utf-8", errors="replace")

    needle = (title_filter or "").strip()
    out: list[EducationRecord] = []
    seen: set[str] = set()
    for href, title_html, date_s in _ITEM_RE.findall(body):
        title = re.sub(r"\s+", " ", _TAG_RE.sub("", title_html)).strip()
        if not title or len(title) < 4:
            continue
        if needle and needle not in title:
            # also try short aliases later via caller
            continue
        link = urljoin(list_url, href.strip())
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
                authors="研招网",
                published_at=_parse_date(date_s),
                source_name=name or default_name,
                external_id=f"chsi:{key}:{link}"[:200],
                institution="研招网",
                tags=["考研", "研招网", key],
                raw={"chsi_key": key, "list_url": list_url},
            )
        )
        if len(out) >= max_results:
            break
    if not out:
        raise ValueError(
            f"研招网列表无有效条目"
            + (f"（过滤「{needle}」后为空）" if needle else "")
            + f"：{list_url}"
        )
    return out


def fetch_chsi_watch(name: str, school: str, *, max_results: int = 30) -> list[EducationRecord]:
    """Aggregate CHSI columns and keep rows mentioning the school."""
    aliases = _school_aliases(school)
    collected: list[EducationRecord] = []
    seen: set[str] = set()
    for key in ("kydt", "zcdh", "fstj"):
        try:
            # Fetch without filter then filter locally with aliases
            rows = fetch_chsi_list(name, key, max_results=40, title_filter=None)
        except Exception:
            continue
        for row in rows:
            if not any(a in row.title for a in aliases):
                continue
            if row.url in seen:
                continue
            seen.add(row.url)
            row.tags = list({*(row.tags or []), school, "关注院校"})[:8]
            collected.append(row)
            if len(collected) >= max_results:
                return collected
    if not collected:
        return []
    return collected


def _school_aliases(school: str) -> list[str]:
    raw = (school or "").strip()
    aliases = [raw]
    # Common short forms
    mapping = {
        "四川大学": ["四川大学", "川大"],
        "北京大学": ["北京大学", "北大"],
        "清华大学": ["清华大学", "清华"],
        "复旦大学": ["复旦大学", "复旦"],
        "上海交通大学": ["上海交通大学", "上海交大", "上交"],
        "浙江大学": ["浙江大学", "浙大"],
        "南京大学": ["南京大学", "南大"],
        "中国科学技术大学": ["中国科学技术大学", "中科大"],
        "哈尔滨工业大学": ["哈尔滨工业大学", "哈工大"],
        "西安交通大学": ["西安交通大学", "西交", "西安交大"],
        "武汉大学": ["武汉大学", "武大"],
        "华中科技大学": ["华中科技大学", "华科"],
        "同济大学": ["同济大学", "同济"],
        "东南大学": ["东南大学", "东南"],
        "天津大学": ["天津大学", "天大"],
        "北京理工大学": ["北京理工大学", "北理工", "北理"],
        "电子科技大学": ["电子科技大学", "电子科大", "成电"],
    }
    for full, shorts in mapping.items():
        if raw in shorts or raw == full:
            return list(dict.fromkeys(shorts))
    if raw.endswith("大学") and len(raw) > 2:
        aliases.append(raw[:-2])
    return list(dict.fromkeys(aliases))


def _parse_date(value: str | None) -> datetime | None:
    text = (value or "").strip().replace("/", "-")
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
