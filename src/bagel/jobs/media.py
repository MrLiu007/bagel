"""Ingest MediaCrawler results into IntelItem rows."""

from __future__ import annotations

import uuid
from typing import Any, Callable

from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, SourceType
from bagel.domain.models import IntelItem
from bagel.integrations.mediacrawler import MediaCrawlerError, run_media_crawl
from bagel.pipeline.category import classify_title
from bagel.pipeline.textutil import headline_from_body, strip_html
from bagel.services import wiki as wiki_svc
from bagel.settings import get_settings
from bagel.storage.repositories import ItemRepository
from sqlalchemy import select

ProgressCallback = Callable[..., None]


def repair_media_duplicate_titles(session: Session, *, limit: int = 500) -> int:
    """Fix persisted media rows where title == full body (common for Weibo)."""
    rows = (
        session.execute(
            select(IntelItem)
            .where(IntelItem.item_type == ItemType.MEDIA_POST)
            .order_by(IntelItem.last_seen_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    fixed = 0
    for item in rows:
        title = strip_html(item.title or "")
        body = strip_html(item.summary or item.content or "")
        if not body or title != body:
            continue
        new_title = headline_from_body(body)
        if not new_title or new_title == title:
            continue
        item.title = new_title[:500]
        fixed += 1
    if fixed:
        session.flush()
    return fixed


def run_collect_media(
    session: Session,
    *,
    platforms: list[str] | None = None,
    keywords: list[str] | None = None,
    owner_id: uuid.UUID | str | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    oid: uuid.UUID | None = None
    if owner_id:
        try:
            oid = owner_id if isinstance(owner_id, uuid.UUID) else uuid.UUID(str(owner_id))
        except (TypeError, ValueError):
            oid = None
    try:
        crawl = run_media_crawl(
            platforms=platforms,
            keywords=keywords,
            settings=settings,
            on_progress=on_progress,
        )
    except MediaCrawlerError as exc:
        return {
            "status": "FAILED",
            "error": exc.message,
            "items_created": 0,
            "items_updated": 0,
            "items_found": 0,
            "platforms_ok": [],
            "platforms_failed": [],
            "hint": (
                "抓取失败（页面应显示 failed，不是成功）。"
                "请查看运行 bagel 的控制台中以 [MediaCrawler/…] 开头的三方日志。"
                "常见原因：搜索无结果、page_size/签名/风控。建议关键词用逗号分隔如 AI,教育。"
            ),
        }

    posts = crawl.posts
    repo = ItemRepository(session)
    created = 0
    updated = 0
    total_posts = max(len(posts), 1)
    for i, post in enumerate(posts, start=1):
        if on_progress:
            # Keep ingest in the final ~1% band so the bar does not jump backwards.
            pct = 99.0 + (1.0 * i / total_posts)
            on_progress(
                current=i,
                total=total_posts,
                percent=min(99.9, round(pct, 1)),
                message=f"入库 {post.title[:40]}",
            )
        item, was_created = repo.upsert_from_normalized(
            item_type=ItemType.MEDIA_POST,
            source_type=SourceType.MEDIA,
            source_id=None,
            title=post.title[:500],
            url=post.url,
            summary=post.summary,
            author=post.author,
            published_at=post.published_at,
            tags=[post.platform, *(keywords or settings.media_keyword_list)][:12],
            category=classify_title(post.title, post.summary or ""),
            metadata={"platform": post.platform, "external_id": post.external_id},
            status=ItemStatus.CANDIDATE,
            score=1.0,
            owner_id=oid,
        )
        if was_created:
            created += 1
            wiki_svc.export_item(item, settings)
        else:
            updated += 1

    # Heal older Weibo/etc. rows that stored identical title and body.
    repair_media_duplicate_titles(session)

    failed = crawl.failed
    hint_parts: list[str] = list(crawl.hints)
    if failed:
        hint_parts.append(
            "失败平台：" + "；".join(f"{f['label']} — {f['error']}" for f in failed)
        )

    # Zero posts is always a failure for UI (never green "success"/PARTIAL-as-success).
    if not posts:
        err = (
            "；".join(f["error"] for f in failed)
            if failed
            else "登录可能成功，但未抓到任何帖子（搜索为空或未写出 jsonl）"
        )
        hint_parts.append(
            "请查看控制台 [MediaCrawler/…] 日志中的 Search preview / items_len。"
            "关键词请用逗号分隔（AI,教育），不要写成「AI 教育」整词。"
        )
        return {
            "status": "FAILED",
            "error": err[:500],
            "items_found": 0,
            "items_created": 0,
            "items_updated": 0,
            "platforms_ok": crawl.succeeded,
            "platforms_failed": failed,
            "hint": " ".join(hint_parts) if hint_parts else None,
        }

    status = "SUCCESS"
    if failed:
        status = "PARTIAL"

    return {
        "status": status,
        "items_found": len(posts),
        "items_created": created,
        "items_updated": updated,
        "platforms_ok": crawl.succeeded,
        "platforms_failed": failed,
        "hint": " ".join(hint_parts) if hint_parts else None,
    }
