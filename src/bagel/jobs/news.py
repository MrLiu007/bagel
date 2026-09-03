"""News collection job — idempotent, isolated failures per source/item.

CN sources run first. Overseas / GLOBAL failures are recorded and skipped so
they never abort domestic collection. Task status is PARTIAL (UI success) when
any source ingested items even if GLOBAL feeds timed out.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bagel.collectors.rss import COLLECTOR_VERSION, RssCollector
from bagel.domain.enums import JobStatus, KeywordScope, Region, SourceType
from bagel.jobs.metrics import elapsed_ms, source_stat
from bagel.pipeline.category import classify_title
from bagel.pipeline.filter import apply_keyword_rules
from bagel.pipeline.keyword_scopes import rules_for_scope
from bagel.pipeline.recency import is_within_lookback, sort_key_published
from bagel.pipeline.textutil import strip_html, truncate
from bagel.settings import Settings, get_settings
from bagel.storage.repositories import (
    ItemRepository,
    JobRunRepository,
    KeywordRuleRepository,
    RawEvidenceRepository,
    SourceRepository,
)

logger = logging.getLogger(__name__)
ProgressCallback = Callable[..., None]

_NETWORKISH = ("NETWORK", "TIMEOUT", "UNREACHABLE", "RATE", "HTTP_ERROR", "PROXY")


def _item_label(title: str | None, url: str | None) -> str:
    label = (title or url or "unknown").strip()
    return label[:80] + ("…" if len(label) > 80 else "")


def _is_networkish(error: str) -> bool:
    upper = error.upper()
    return any(tok in upper for tok in _NETWORKISH)


def run_collect_news(
    session: Session,
    settings: Settings | None = None,
    *,
    on_progress: ProgressCallback | None = None,
    cn_only: bool = False,
) -> dict[str, Any]:
    settings = settings or get_settings()
    jobs = JobRunRepository(session)
    run = jobs.start("collect_news")

    sources = list(SourceRepository(session).list_enabled())
    # News job only: RSS / RSSHub / Manual — never PAPER / STOCK / MEDIA / …
    sources = [
        s
        for s in sources
        if s.source_type in {SourceType.RSS, SourceType.RSSHUB, SourceType.MANUAL}
    ]
    if cn_only:
        sources = [s for s in sources if s.region == Region.CN]
    elif not settings.enable_overseas_sources:
        sources = [s for s in sources if s.region != Region.GLOBAL]

    # Domestic first so GLOBAL network outages never delay CN ingest.
    sources.sort(key=lambda s: (0 if s.region == Region.CN else 1, s.priority, s.name))

    rules = rules_for_scope(
        KeywordRuleRepository(session).list_enabled(),
        KeywordScope.NEWS,
    )
    collector = RssCollector(settings)
    items_repo = ItemRepository(session)
    evidence_repo = RawEvidenceRepository(session)

    found = created = updated = skipped = 0
    errors: list[str] = []
    source_stats: list[dict[str, Any]] = []
    sources_ok = 0
    cn_ok = 0
    global_failed = 0
    total = len(sources)
    lookback_days = settings.collect_lookback_days
    job_t0 = time.perf_counter()

    def progress(i: int, message: str) -> None:
        if on_progress:
            on_progress(current=i, total=total, message=message)

    logger.info(
        "collect_news.start sources=%s lookback_days=%s cn_only=%s overseas=%s",
        total,
        lookback_days,
        cn_only,
        settings.enable_overseas_sources,
    )
    progress(0, f"准备采集 {total} 个新闻源（近 {lookback_days} 天）…")

    # Interest INCLUDE / EXCLUDE filtered by KeywordScope.NEWS.

    for index, source in enumerate(sources, start=1):
        region_tag = "CN" if source.region == Region.CN else "GLOBAL"
        src_t0 = time.perf_counter()
        src_found = src_created = src_updated = src_skipped = 0
        progress(index - 1, f"采集中 ({index}/{total})：{source.name}")
        try:
            result = collector.collect_source(source)
        except Exception as exc:  # noqa: BLE001 — keep other sources running
            session.rollback()
            SourceRepository(session).mark_error(source, "COLLECT_ERROR")
            errors.append(f"[{region_tag}] {source.name}: {exc}")
            if source.region == Region.GLOBAL:
                global_failed += 1
            logger.warning(
                "collect_news.source_exception name=%s region=%s err=%s",
                source.name,
                region_tag,
                exc,
            )
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
            progress(index, f"跳过：{source.name}（异常）")
            continue

        if not result.ok:
            code = result.error_code or "UNKNOWN_ERROR"
            SourceRepository(session).mark_error(source, code)
            detail = (result.error_message or code)[:120]
            errors.append(f"[{region_tag}] {source.name}: {code} ({detail})")
            if source.region == Region.GLOBAL:
                global_failed += 1
            logger.warning(
                "collect_news.source_failed name=%s region=%s code=%s",
                source.name,
                region_tag,
                code,
            )
            source_stats.append(
                source_stat(
                    source.name,
                    status="failed",
                    region=region_tag,
                    source_id=str(source.id),
                    duration_ms=elapsed_ms(src_t0),
                    error=f"{code} ({detail})",
                )
            )
            progress(index, f"跳过：{source.name} ({code})")
            continue

        SourceRepository(session).mark_success(source)
        sources_ok += 1
        if source.region == Region.CN:
            cn_ok += 1

        # Newest published first so early abort / UI mid-run sees fresh items.
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
                    tags = list(
                        {
                            *filt.matched_include,
                            *filt.matched_boost,
                        }
                    )
                    summary = truncate(normalized.summary or normalized.content, 400) or None
                    category = classify_title(normalized.title, summary)
                    _item, was_created = items_repo.upsert_from_normalized(
                        item_type=normalized.item_type,
                        source_type=normalized.source_type,
                        source_id=source.id,
                        title=strip_html(normalized.title) or normalized.title,
                        url=normalized.url,
                        summary=summary,
                        content=normalized.content,
                        author=normalized.author,
                        language=normalized.language,
                        published_at=normalized.published_at,
                        tags=tags,
                        topics=list({*(normalized.topics or []), category}),
                        category=category,
                        metadata={
                            **normalized.metadata,
                            "region": source.region,
                            "source_name": source.name,
                            "filter": {
                                "include": filt.matched_include,
                                "exclude": filt.matched_exclude,
                                "boost": filt.matched_boost,
                            },
                        },
                        raw_evidence_id=evidence.id,
                        status=filt.status,
                        score=filt.score,
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
                errors.append(f"[{region_tag}] {source.name}/{label}: {exc.__class__.__name__}")
                continue
        # Commit per source so UI can see partial data if refreshed mid-run.
        try:
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            errors.append(f"[{region_tag}] {source.name}: commit failed ({exc.__class__.__name__})")
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
        # Domestic ingest succeeded; overseas failures are degraded, not fatal.
        status = JobStatus.PARTIAL
        error_message = "; ".join(errors[:10])
    elif errors and (created + updated) == 0:
        only_global_network = (
            global_failed > 0
            and cn_ok == 0
            and all(_is_networkish(e) or "[GLOBAL]" in e for e in errors)
            and any("[GLOBAL]" in e for e in errors)
        )
        if sources_ok > 0 or found > 0 or only_global_network:
            # Fetched-but-filtered, or only overseas network issues → degraded OK.
            status = JobStatus.PARTIAL
        elif any(_is_networkish(e) for e in errors):
            status = JobStatus.PARTIAL
        else:
            status = JobStatus.FAILED
        error_message = "; ".join(errors[:10])
        error_code = "COLLECT_ERRORS"

    hint = None
    if global_failed and (created + updated) > 0:
        hint = f"海外源失败 {global_failed} 个已跳过，国内采集继续（新建 {created}）"
    elif errors:
        hint = error_message

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
    logger.info(
        "collect_news.done status=%s found=%s created=%s updated=%s skipped=%s "
        "sources_ok=%s cn_ok=%s global_failed=%s errors=%s",
        status,
        found,
        created,
        updated,
        skipped,
        sources_ok,
        cn_ok,
        global_failed,
        len(errors),
    )
    if errors:
        logger.warning("collect_news.errors %s", "; ".join(errors[:10]))
    progress(total, f"新闻采集结束：新建 {created}，更新 {updated}，跳过 {skipped}")
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
        "error": error_message or hint,
        "hint": hint,
        "sources_ok": sources_ok,
        "cn_ok": cn_ok,
        "global_failed": global_failed,
    }
