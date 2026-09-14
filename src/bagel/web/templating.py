"""Shared Jinja2 environment for all HTML routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from starlette.requests import Request

from bagel.domain.enums import ItemType
from bagel.services.av_bridge import (
    can_enrich_media_transcript,
    is_importable_media_post,
    item_has_rich_transcript,
    linked_av_id,
)
from bagel.web.proxy_prefix import app_url
from bagel.pipeline.textutil import (
    format_datetime,
    split_title_and_body,
    strip_html,
    truncate,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["plain"] = truncate
templates.env.filters["fmt_dt"] = format_datetime


@pass_context
def _url_with_prefix(ctx: dict, path: str) -> str:
    request = ctx.get("request")
    if not isinstance(request, Request):
        return path
    return app_url(request, path)


templates.env.globals["u"] = _url_with_prefix


def present_item(item, *, preview: bool | None = None, source_name: str | None = None) -> dict:
    """View-model so templates do not depend on custom filters.

    Lists show full summary/content. Media posts dedupe identical title/body.
    WeChat articles: list = short plain summary + detail link; detail = rich HTML.
    """
    list_mode = preview is not False
    raw_title = strip_html(getattr(item, "title", None) or "")
    item_type = getattr(item, "item_type", None)
    meta = getattr(item, "metadata_", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    wechat_mp = meta.get("wechat_mp") if isinstance(meta.get("wechat_mp"), dict) else {}
    raw_content = getattr(item, "content", None) or ""
    content_is_html = bool(wechat_mp.get("content_is_html")) or (
        item_type == ItemType.WECHAT_ARTICLE and "<" in raw_content and ">" in raw_content
    )
    # List never embeds full 公众号 HTML (images/video belong on detail page).
    if item_type == ItemType.WECHAT_ARTICLE and list_mode:
        summary_html = ""
        raw_body = strip_html(item.summary or raw_content)
    elif content_is_html and raw_content:
        summary_html = raw_content
        raw_body = strip_html(item.summary or raw_content)
    else:
        summary_html = ""
        raw_body = strip_html(item.summary or raw_content)
    title, body = split_title_and_body(raw_title, raw_body)
    if item_type == ItemType.WECHAT_ARTICLE and list_mode:
        body = truncate(body or raw_body, 140)

    stock_meta = {}
    if isinstance(meta.get("stock"), dict):
        stock_meta = meta["stock"]
    tickers = []
    for t in stock_meta.get("tickers") or []:
        if isinstance(t, dict) and t.get("symbol"):
            tickers.append(
                {
                    "symbol": t["symbol"],
                    "name": t.get("name") or t["symbol"],
                }
            )
    sentiment = stock_meta.get("sentiment") or ""
    themes = [str(x) for x in (stock_meta.get("themes") or []) if x][:4]

    published = item.published_at
    if published is not None:
        time_label = format_datetime(published)
        time_prefix = "发布 "
    else:
        # Do not fall back to入库时间 — that misleads “latest by publish time”.
        time_label = "时间未知"
        time_prefix = ""
    first_seen = getattr(item, "first_seen_at", None)
    is_new = False
    if first_seen is not None:
        fs = first_seen if first_seen.tzinfo else first_seen.replace(tzinfo=UTC)
        is_new = fs >= datetime.now(UTC) - timedelta(hours=24)

    download_status = ""
    download_label = ""
    local_play_url = ""
    if item_type == ItemType.AV and isinstance(meta, dict):
        dl = meta.get("download") if isinstance(meta.get("download"), dict) else {}
        download_status = str(dl.get("status") or "none")
        labels = {
            "none": "未下载",
            "pending": "下载中",
            "done": "已下载",
            "failed": "下载失败",
            "skipped_drm": "DRM 不可用",
        }
        download_label = labels.get(download_status, download_status)
        if download_status == "done" and dl.get("local_path"):
            local_play_url = f"/api/av/files/{item.id}"

    av_detail_url = ""
    show_av_import = False
    show_av_enrich = False
    has_rich_transcript = False
    if item_type == ItemType.MEDIA_POST:
        av_id = linked_av_id(item)
        if av_id:
            av_detail_url = f"/av/items/{av_id}"
        elif is_importable_media_post(item):
            show_av_import = True
        show_av_enrich = can_enrich_media_transcript(item)
        has_rich_transcript = item_has_rich_transcript(item)
    elif item_type == ItemType.AV:
        has_rich_transcript = item_has_rich_transcript(item)

    row = {
        "id": str(item.id),
        "url": item.url,
        "title": title or raw_title,
        "category": item.category,
        "author": getattr(item, "author", None) or "",
        "source_name": source_name or "",
        "source_id": str(getattr(item, "source_id", "") or ""),
        "tags": list(item.tags or []),
        "summary": body or raw_body,
        "summary_html": summary_html,
        "show_related": item_type
        in {
            ItemType.NEWS,
            ItemType.PAPER,
            ItemType.STOCK_NEWS,
            ItemType.GITHUB_REPO,
            ItemType.GITHUB_RELEASE,
            ItemType.MEDIA_POST,
            ItemType.MODEL,
            ItemType.EDUCATION,
            ItemType.AV,
        },
        "tickers": tickers,
        "sentiment": sentiment,
        "themes": themes,
        "time_label": time_label,
        "time_prefix": time_prefix,
        "is_favorite": bool(item.is_favorite),
        "is_top": bool(item.is_top),
        "is_deep_read": bool(item.is_deep_read),
        "is_new": is_new,
        "item_type": item.item_type,
        "status": item.status,
        "download_status": download_status,
        "download_label": download_label,
        "local_play_url": local_play_url,
        "show_av_download": item_type == ItemType.AV,
        "detail_url": (
            f"/av/items/{item.id}"
            if item_type == ItemType.AV
            else f"/wechat/articles/{item.id}"
            if item_type == ItemType.WECHAT_ARTICLE
            else ""
        ),
        "show_av_import": show_av_import,
        "av_detail_url": av_detail_url,
        "show_av_enrich": show_av_enrich,
        "has_rich_transcript": has_rich_transcript,
        "show_paper_parse": False,
        "show_paper_probe": False,
        "paper_parse_label": "",
        "show_github_learn": item_type
        in {ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE},
        "github_learn_url": (
            f"/github/learn/{item.id}"
            if item_type in {ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE}
            else ""
        ),
        "github_learn_done": bool(
            item_type in {ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE}
            and isinstance(meta, dict)
            and isinstance(meta.get("learn"), dict)
            and meta["learn"].get("status") in {"done", "indexed"}
        ),
    }
    if item_type == ItemType.PAPER:
        from bagel.collectors.papers import paper_has_resolvable_pdf

        parsed = (
            isinstance(meta, dict)
            and isinstance(meta.get("parse"), dict)
            and meta["parse"].get("status") == "done"
        )
        has_pdf = paper_has_resolvable_pdf(
            page_url=item.url,
            external_id=str((meta or {}).get("external_id") or ""),
            raw=(meta or {}).get("raw") if isinstance((meta or {}).get("raw"), dict) else None,
            stored_pdf_url=str((meta or {}).get("pdf_url") or "") or None,
        )
        row["paper_parse_label"] = "已解析正文" if parsed else ""
        row["show_paper_parse"] = bool(has_pdf and not parsed)
        row["show_paper_probe"] = bool(not has_pdf and not parsed)
    return row
