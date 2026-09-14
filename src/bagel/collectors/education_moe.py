"""Direct HTML list fetch for 教育部 (moe.gov.cn).

RSSHub ``/gov/moe/*`` often returns 502 when upstream layout/WAF changes.
Bagel falls back to these official list pages (no RSSHub dependency).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx

from bagel.collectors.education import EducationRecord, USER_AGENT
from bagel.integrations.http import build_http_client
from bagel.settings import get_settings

MOE_HOME = "https://www.moe.gov.cn/"

# RSSHub type → official list page (more stable than homepage widgets).
MOE_LIST_PAGES: dict[str, tuple[str, str]] = {
    "newest_file": (
        "https://www.moe.gov.cn/jyb_xxgk/moe_1777/moe_1778/",
        "教育部 · 最新文件",
    ),
    "notice": (
        "https://www.moe.gov.cn/jyb_xxgk/s5743/s5744/",
        "教育部 · 公告公示",
    ),
    "policy_anal": (
        "https://www.moe.gov.cn/jyb_xwfb/s271/",
        "教育部 · 政策解读",
    ),
    "edu_ministry_news": (
        "https://www.moe.gov.cn/jyb_xwfb/gzdt_gzdt/",
        "教育部 · 工作动态",
    ),
    "edu_focus_news": (
        "https://www.moe.gov.cn/jyb_sy/sy_jyyw/",
        "教育部 · 教育要闻",
    ),
}

_TAG_RE = re.compile(r"<[^>]+>")
_ITEM_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>\s*'
    r'(?:<span[^>]*>\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*</span>)?',
    re.I | re.S,
)


def moe_type_from_path(path: str) -> str | None:
    """Return moe type key from RSSHub path ``/gov/moe/{type}`` (or absolute URL path)."""
    raw = (path or "").strip()
    # Strip query / fragment
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    # Absolute URL → path
    if "://" in raw:
        from urllib.parse import urlparse

        raw = urlparse(raw).path or ""
    raw = raw.rstrip("/")
    marker = "/gov/moe/"
    low = raw.lower()
    idx = low.find(marker)
    if idx < 0:
        return None
    key = raw[idx + len(marker) :].strip("/").split("/", 1)[0].lower()
    return key if key in MOE_LIST_PAGES else None


def fetch_moe_list(
    name: str,
    moe_type: str,
    *,
    max_results: int = 30,
) -> list[EducationRecord]:
    """Scrape an official MOE list page into EducationRecord rows."""
    page = MOE_LIST_PAGES.get(moe_type)
    if not page:
        raise ValueError(f"未知教育部分类：{moe_type}")
    list_url, default_name = page
    settings = get_settings()
    with build_http_client(
        settings,
        timeout=40.0,
        force_proxy=False,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": MOE_HOME,
        },
    ) as client:
        resp = client.get(list_url)
        resp.raise_for_status()
        # MOE pages are typically utf-8; httpx may mis-detect.
        body = resp.content.decode("utf-8", errors="replace")

    out: list[EducationRecord] = []
    seen: set[str] = set()
    for href, title_html, date_s in _ITEM_RE.findall(body):
        title = re.sub(r"\s+", " ", _TAG_RE.sub("", title_html)).strip()
        if not title or len(title) < 4:
            continue
        if href in {"./", "#", "javascript:;"} or href.endswith("/"):
            continue
        # Skip chrome / sidebar noise.
        if any(x in href for x in ("sy_wb", "javascript", "void(0)")):
            continue
        if not re.search(r"t20\d{6,}|/20\d{2}/", href):
            continue
        link = urljoin(list_url, href.strip())
        from bagel.pipeline.education_noise import is_education_noise

        if is_education_noise(title, link):
            continue
        if link in seen:
            continue
        seen.add(link)
        published = _parse_ymd(date_s)
        out.append(
            EducationRecord(
                title=title[:500],
                url=link,
                summary="",
                authors="教育部",
                published_at=published,
                source_name=name or default_name,
                external_id=f"moe:{moe_type}:{link}"[:200],
                institution="教育部",
                tags=["K12", "教育部", moe_type],
                raw={"moe_type": moe_type, "list_url": list_url},
            )
        )
        if len(out) >= max_results:
            break

    if not out:
        raise ValueError(f"教育部列表页无有效条目：{list_url}")
    return out


def _parse_ymd(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def is_moe_rsshub_path(path: str) -> bool:
    return moe_type_from_path(path) is not None
