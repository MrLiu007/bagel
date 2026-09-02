"""Stock news collection — STOCK sources with stocks-scoped keyword rules."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bagel.collectors.rss import COLLECTOR_VERSION, RssCollector
from bagel.domain.enums import ItemType, JobStatus, KeywordScope, Region, SourceType
from bagel.jobs.metrics import elapsed_ms, source_stat
from bagel.pipeline.filter import apply_keyword_rules
from bagel.pipeline.keyword_scopes import rules_for_scope
from bagel.pipeline.recency import is_within_lookback, sort_key_published
from bagel.pipeline.stock_extract import enrich_stock_text
from bagel.pipeline.textutil import strip_html, truncate
from bagel.settings import Settings, get_settings
from bagel.storage.repositories import (
    ItemRepository,
    JobRunRepository,
    KeywordRuleRepository,
    RawEvidenceRepository,
    SourceRepository,
)

ProgressCallback = Callable[..., None]


def _item_label(title: str | None, url: str | None) -> str:
    label = (title or url or "unknown").strip()
    return label[:80] + ("…" if len(label) > 80 else "")


def run_collect_stocks(
    session: Session,
    settings: Settings | None = None,
    *,
    on_progress: ProgressCallback | None = None,
    cn_only: bool = False,
    owner_id: Any = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    oid = None
    if owner_id:
        from uuid import UUID

        oid = owner_id if isinstance(owner_id, UUID) else UUID(str(owner_id))
    jobs = JobRunRepository(session)
    run = jobs.start("collect_stocks")

    sources = [
        s
        for s in SourceRepository(session).list_enabled()
        if s.source_type == SourceType.STOCK
    ]
    if not sources:
        jobs.finish(
            run,
            status=JobStatus.FAILED,
            items_found=0,
            items_created=0,
            items_updated=0,
            error_code="NO_SOURCES",
            error_message="未配置股票数据源：请在系统设置 → 股票数据源中添加",
        )
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
        if on_progress:
            on_progress(current=1, total=1, message="未配置股票数据源")
        return {
            "run_id": str(run.id),
            "status": JobStatus.FAILED,
            "error": "未配置股票数据源：请在系统设置 → 股票数据源中添加",
            "items_found": 0,
            "items_created": 0,
            "items_updated": 0,
            "items_skipped": 0,
            "duration_ms": 0,
            "source_stats": [],
            "errors": [],
        }

    if cn_only:
        sources = [s for s in sources if s.region == Region.CN]
    elif not settings.enable_overseas_sources:
        sources = [s for s in sources if s.region != Region.GLOBAL]

    # Stocks-scoped INCLUDE / EXCLUDE / BOOST (settings → 股票数据源 / 系统排除词).
    rules = rules_for_scope(
        KeywordRuleRepository(session).list_enabled(),
        KeywordScope.STOCKS,
    )
    collector = RssCollector(settings)
    items_repo = ItemRepository(session)
    evidence_repo = RawEvidenceRepository(session)

    found = created = updated = skipped = 0
    errors: list[str] = []
    source_stats: list[dict[str, Any]] = []
    total = len(sources)
    lookback_days = settings.collect_lookback_days
    job_t0 = time.perf_counter()

    def progress(i: int, message: str) -> None:
        if on_progress:
            on_progress(current=i, total=total, message=message)

    progress(0, f"准备采集 {total} 个股票源（近 {lookback_days} 天）…")

    for index, source in enumerate(sources, start=1):
        src_t0 = time.perf_counter()
        src_found = src_created = src_updated = src_skipped = 0
        region_tag = "CN" if source.region == Region.CN else "GLOBAL"
        progress(index - 1, f"采集中 ({index}/{total})：{source.name}")
        try:
            result = collector.collect_source(source)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            SourceRepository(session).mark_error(source, "COLLECT_ERROR")
            errors.append(f"{source.name}: {exc}")
            source_stats.append(
                source_stat(
                    source.name,
                    status="failed",
                    region=region_tag,
                    source_id=str(source.id),
                    duration_ms=elapsed_ms(src_t0),
                    error=str(exc),
                )
            )
            progress(index, f"失败：{source.name}")
            continue

        if not result.ok:
            SourceRepository(session).mark_error(source, result.error_code or "UNKNOWN_ERROR")
            errors.append(f"{source.name}: {result.error_code}")
            source_stats.append(
                source_stat(
                    source.name,
                    status="failed",
                    region=region_tag,
                    source_id=str(source.id),
                    duration_ms=elapsed_ms(src_t0),
                    error=str(result.error_code),
                )
            )
            progress(index, f"失败：{source.name} ({result.error_code})")
            continue

        SourceRepository(session).mark_success(source)
        feed_items = sorted(
            result.items,
            key=lambda n: sort_key_published(n.published_at),
            reverse=True,
        )
        for normalized in feed_items:
            if not is_within_lookback(
                normalized.published_at,
                days=lookback_days,
                keep_unknown=False,
            ):
                skipped += 1
                src_skipped += 1
                continue
            found += 1
            src_found += 1
            label = _item_label(normalized.title, normalized.url)
            try:
                with session.begin_nested():
                    filt = apply_keyword_rules(normalized.title, normalized.summary, rules)
                    evidence = evidence_repo.create(
                        source_type=normalized.source_type,
                        source_url=source.url,
                        external_id=normalized.external_id,
                        raw_payload=normalized.raw_payload,
                        http_status=normalized.http_status,
                        etag=normalized.etag,
                        last_modified=normalized.last_modified,
                        collector_version=COLLECTOR_VERSION,
                    )
                    tags = list({*filt.matched_include, *filt.matched_boost})
                    summary = truncate(normalized.summary or normalized.content, 400) or None
                    enrichment = None
                    category = "其他"
                    stock_meta: dict = {}
                    if settings.enable_stock_enrichment:
                        enrichment = enrich_stock_text(
                            strip_html(normalized.title) or normalized.title,
                            summary,
                        )
                        category = enrichment.category
                        stock_meta = enrichment.as_metadata()
                        for label in enrichment.tag_labels():
                            if label not in tags:
                                tags.append(label)
                    meta = {
                        **normalized.metadata,
                        "region": source.region,
                        "domain": "stock",
                        "filter": {
                            "include": filt.matched_include,
                            "exclude": filt.matched_exclude,
                            "boost": filt.matched_boost,
                        },
                    }
                    if stock_meta:
                        meta["stock"] = stock_meta
                    _item, was_created = items_repo.upsert_from_normalized(
                        item_type=ItemType.STOCK_NEWS,
                        source_type=SourceType.STOCK,
                        source_id=source.id,
                        title=strip_html(normalized.title) or normalized.title,
                        url=normalized.url,
                        summary=summary,
                        content=normalized.content,
                        author=normalized.author,
                        language=normalized.language,
                        published_at=normalized.published_at,
                        tags=tags[:16],
                        topics=list(
                            {
                                *(normalized.topics or []),
                                category,
                                "stock",
                                *([t.symbol for t in enrichment.tickers[:4]] if enrichment else []),
                            }
                        ),
                        category=category,
                        metadata=meta,
                        raw_evidence_id=evidence.id,
                        status=filt.status,
                        score=filt.score if filt.accepted else filt.score,
                        owner_id=oid,
                    )
                    if was_created:
                        created += 1
                        src_created += 1
                    else:
                        updated += 1
                        src_updated += 1
            except (SQLAlchemyError, ValueError, TypeError) as exc:
                skipped += 1
                src_skipped += 1
                errors.append(f"{source.name}/{label}: {exc.__class__.__name__}")
                continue
        try:
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            errors.append(f"{source.name}: commit failed ({exc.__class__.__name__})")
            source_stats.append(
                source_stat(
                    source.name,
                    status="failed",
                    region=region_tag,
                    source_id=str(source.id),
                    items_found=src_found,
                    items_created=src_created,
                    items_updated=src_updated,
                    items_skipped=src_skipped,
                    duration_ms=elapsed_ms(src_t0),
                    error=f"commit failed ({exc.__class__.__name__})",
                )
            )
            progress(index, f"提交失败：{source.name}")
            continue
        source_stats.append(
            source_stat(
                source.name,
                status="success",
                region=region_tag,
                source_id=str(source.id),
                items_found=src_found,
                items_created=src_created,
                items_updated=src_updated,
                items_skipped=src_skipped,
                duration_ms=elapsed_ms(src_t0),
            )
        )
        progress(index, f"完成：{source.name}（累计新建 {created}，跳过 {skipped}）")
    status = JobStatus.SUCCESS
    error_code = None
    error_message = None
    if errors and (created + updated) > 0:
        status = JobStatus.PARTIAL
        error_message = "; ".join(errors[:10])
    elif errors and (created + updated) == 0:
        status = JobStatus.PARTIAL if found > 0 or any("NETWORK" in e for e in errors) else JobStatus.FAILED
        error_message = "; ".join(errors[:10])
        error_code = "COLLECT_ERRORS"

    jobs.finish(
        run,
        status=status,
        items_found=found,
        items_created=created,
        items_updated=updated,
        error_code=error_code,
        error_message=error_message,
    )
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
    progress(total, f"股票采集结束：新建 {created}，更新 {updated}，跳过 {skipped}")
    return {
        "run_id": str(run.id),
        "status": status,
        "items_found": found,
        "items_created": created,
        "items_updated": updated,
        "items_skipped": skipped,
        "duration_ms": elapsed_ms(job_t0),
        "source_stats": source_stats,
        "errors": errors,
    }
