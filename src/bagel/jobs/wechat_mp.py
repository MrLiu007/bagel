"""Ingest WeChat official-account articles fetched by URL into IntelItem."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, KeywordScope, SourceType
from bagel.integrations.wechat_mp import WechatMpError, fetch_mp_article
from bagel.integrations.wechat_mp_media import localize_article_html
from bagel.pipeline.category import classify_title
from bagel.pipeline.filter import apply_keyword_rules
from bagel.pipeline.keyword_scopes import rules_for_scope
from bagel.pipeline.textutil import strip_html
from bagel.services import wiki as wiki_svc
from bagel.settings import NetworkMode, get_settings
from bagel.storage.repositories import ItemRepository, KeywordRuleRepository


def ingest_wechat_article_url(
    session: Session,
    url: str,
    *,
    owner_id: UUID | None = None,
    source_id: UUID | None = None,
    fetched_via: str = "url",
    localize_media: bool = True,
    account_hint: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    try:
        article = fetch_mp_article(url, settings=settings)
    except WechatMpError as exc:
        return {"ok": False, "error": exc.message}

    rules = rules_for_scope(
        KeywordRuleRepository(session).list_enabled(),
        KeywordScope.WECHAT,
    )
    plain_for_filter = strip_html(article.content) if article.content_is_html else (
        article.content or article.summary
    )
    filt = apply_keyword_rules(article.title, plain_for_filter or "", rules)
    status = filt.status if filt.accepted else ItemStatus.REJECTED
    account = article.account or (account_hint or "").strip()
    tags = ["wechat", "wechat_mp"]
    if account:
        tags.append(account[:40])

    repo = ItemRepository(session)
    item, created = repo.upsert_from_normalized(
        item_type=ItemType.WECHAT_ARTICLE,
        source_type=SourceType.WECHAT,
        source_id=source_id,
        title=article.title,
        url=article.url,
        summary=article.summary,
        content=article.content,
        author=account or None,
        published_at=article.published_at or datetime.now(UTC),
        tags=tags[:12],
        category=classify_title(article.title, article.summary),
        metadata={
            "wechat_mp": {
                "account": account,
                "fetched_via": fetched_via,
                "content_is_html": article.content_is_html,
                "proxy_used": bool(
                    settings.proxy_url and settings.network_mode != NetworkMode.DIRECT
                ),
                "media_localized": False,
            },
            "filter": {
                "include": filt.matched_include,
                "exclude": filt.matched_exclude,
                "boost": filt.matched_boost,
            },
        },
        status=status,
        score=1.0 + filt.score,
        owner_id=owner_id,
    )

    media_info: dict[str, Any] = {}
    if localize_media and article.content_is_html and article.content:
        new_html, media_info = localize_article_html(
            article.content,
            item_id=item.id,
            page_url=article.url,
            settings=settings,
        )
        item.content = new_html
        meta = dict(item.metadata_ or {})
        mp = dict(meta.get("wechat_mp") or {})
        mp.update(
            {
                "content_is_html": True,
                "media_localized": True,
                "asset_count": media_info.get("asset_count", 0),
                "media_skipped": media_info.get("skipped") or [],
            }
        )
        meta["wechat_mp"] = mp
        item.metadata_ = meta
        session.add(item)
        session.commit()
        session.refresh(item)

    if created:
        wiki_svc.export_item(item, settings)
    return {
        "ok": True,
        "created": created,
        "item_id": str(item.id),
        "title": item.title,
        "account": account,
        "status": status,
        "detail_url": f"/wechat/articles/{item.id}",
        "asset_count": int(media_info.get("asset_count") or 0),
        "media_skipped": len(media_info.get("skipped") or []),
    }


def run_collect_wechat_mp(
    session: Session,
    settings=None,
    *,
    on_progress=None,
    owner_id: UUID | str | None = None,
    max_per_source: int = 6,
) -> dict[str, Any]:
    """Discover + ingest articles for all enabled wechat:mp IntelSource rows."""
    import time
    import uuid as uuid_mod

    from sqlalchemy import select

    from bagel.domain.models import IntelSource
    from bagel.integrations.wechat_mp_discover import (
        discover_articles,
        parse_source_url,
    )
    from bagel.jobs.metrics import elapsed_ms, source_stat
    from bagel.settings import Settings, get_settings as _gs

    settings = settings or _gs()
    if not isinstance(settings, Settings):
        settings = _gs()

    sources = list(
        session.scalars(
            select(IntelSource)
            .where(
                IntelSource.source_type == SourceType.WECHAT,
                IntelSource.enabled.is_(True),
                IntelSource.url.like("wechat:mp:%"),
            )
            .order_by(IntelSource.priority)
        ).all()
    )
    if not sources:
        return {
            "status": "FAILED",
            "error": "未订阅公众号：请在微信 → 公众号页按名称添加订阅",
            "items_created": 0,
            "items_found": 0,
            "duration_ms": 0,
            "source_stats": [],
        }

    oid: UUID | None = None
    if owner_id:
        try:
            oid = owner_id if isinstance(owner_id, UUID) else uuid_mod.UUID(str(owner_id))
        except (TypeError, ValueError):
            oid = None

    created = found = 0
    errors: list[str] = []
    source_stats: list[dict[str, Any]] = []
    job_t0 = time.perf_counter()
    total = len(sources)

    for i, src in enumerate(sources, start=1):
        src_t0 = time.perf_counter()
        src_created = 0
        ref = parse_source_url(src.url or "")
        if on_progress:
            on_progress(
                current=i - 1,
                total=total,
                message=f"发现「{src.name}」近期文章…",
            )
        try:
            articles, disc_meta = discover_articles(
                ref, settings=settings, limit=max_per_source
            )
        except Exception as exc:  # noqa: BLE001
            err = f"{src.name}: 发现失败 {str(exc)[:120]}"
            errors.append(err)
            source_stats.append(
                source_stat(
                    name=src.name,
                    status="failed",
                    error=err,
                    duration_ms=elapsed_ms(src_t0),
                    source_id=str(src.id),
                )
            )
            src.last_error_code = "DISCOVER_FAILED"
            session.add(src)
            continue

        if not articles:
            from bagel.integrations.wechat_mp_discover import empty_discover_hint

            msg = empty_discover_hint(src.name, disc_meta)
            errors.append(msg)
            source_stats.append(
                source_stat(
                    name=src.name,
                    status="failed",
                    error=msg,
                    duration_ms=elapsed_ms(src_t0),
                    source_id=str(src.id),
                )
            )
            src.last_error_code = "EMPTY"
            session.add(src)
            continue

        # Persist resolved wxid / wewe feed back into source URL
        resolved = (disc_meta.get("resolved_wxid") or "").strip()
        wewe_meta = disc_meta.get("wewe") if isinstance(disc_meta.get("wewe"), dict) else {}
        wewe_fid = (wewe_meta.get("feed_id") or "").strip()
        if resolved or wewe_fid:
            from bagel.integrations.wechat_mp_discover import build_source_url
            from bagel.integrations.wewe_rss import WeweRssClient

            try:
                feed = ref.feed_url
                if wewe_fid and not feed:
                    client = WeweRssClient(settings)
                    if client.enabled:
                        feed = client.feed_json_url(wewe_fid, limit=12)
                src.url = build_source_url(
                    name=ref.name or src.name,
                    wxid=resolved or ref.wxid,
                    biz=ref.biz,
                    feed_url=feed,
                )
                session.add(src)
            except ValueError:
                pass

        for art in articles:
            found += 1
            if on_progress:
                on_progress(
                    current=i - 1,
                    total=total,
                    message=f"「{src.name}」拉取：{(art.title or art.url)[:40]}…",
                )
            result = ingest_wechat_article_url(
                session,
                art.url,
                owner_id=oid,
                source_id=src.id,
                fetched_via="subscription",
                localize_media=True,
                account_hint=src.name,
            )
            if result.get("ok") and result.get("created"):
                created += 1
                src_created += 1
            elif not result.get("ok"):
                errors.append(f"{src.name}: {result.get('error')}")
            time.sleep(0.8)

        from datetime import datetime as dt

        src.last_success_at = dt.now(UTC)
        src.last_error_code = None
        session.add(src)
        source_stats.append(
            source_stat(
                name=src.name,
                status="success",
                items_created=src_created,
                items_found=len(articles),
                duration_ms=elapsed_ms(src_t0),
                source_id=str(src.id),
            )
        )

    session.commit()
    status = "SUCCESS"
    if errors and created == 0 and found == 0:
        status = "FAILED"
    elif errors:
        status = "PARTIAL"
    return {
        "status": status,
        "items_created": created,
        "items_found": found,
        "duration_ms": elapsed_ms(job_t0),
        "source_stats": source_stats,
        "errors": errors[:20],
    }


def relocalize_item_media(session: Session, item_id: UUID) -> dict[str, Any]:
    """Re-download remote media for an existing article (detail page repair)."""
    repo = ItemRepository(session)
    item = repo.get(item_id)
    if item is None or item.item_type != ItemType.WECHAT_ARTICLE:
        return {"ok": False, "error": "条目不存在"}
    settings = get_settings()
    html = item.content or ""
    if not html or "<" not in html:
        return {"ok": False, "error": "无正文可处理"}
    new_html, media_info = localize_article_html(
        html,
        item_id=item.id,
        page_url=item.url or "https://mp.weixin.qq.com/",
        settings=settings,
    )
    item.content = new_html
    meta = dict(item.metadata_ or {})
    mp = dict(meta.get("wechat_mp") or {})
    mp.update(
        {
            "content_is_html": True,
            "media_localized": True,
            "asset_count": media_info.get("asset_count", 0),
            "media_skipped": media_info.get("skipped") or [],
        }
    )
    meta["wechat_mp"] = mp
    item.metadata_ = meta
    session.add(item)
    session.commit()
    return {
        "ok": True,
        "item_id": str(item.id),
        "asset_count": media_info.get("asset_count", 0),
        "skipped": media_info.get("skipped") or [],
    }
