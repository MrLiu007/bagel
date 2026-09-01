"""News collection job — idempotent, isolated failures per source/item."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bagel.collectors.rss import COLLECTOR_VERSION, RssCollector
from bagel.domain.enums import JobStatus, Region, SourceType
from bagel.pipeline.category import classify_title
from bagel.pipeline.filter import apply_keyword_rules
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

ProgressCallback = Callable[..., None]


def _item_label(title: str | None, url: str | None) -> str:
    label = (title or url or "unknown").strip()
    return label[:80] + ("…" if len(label) > 80 else "")


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

    rules = KeywordRuleRepository(session).list_enabled()
    collector = RssCollector(settings)
    items_repo = ItemRepository(session)
    evidence_repo = RawEvidenceRepository(session)

    found = created = updated = skipped = 0
    errors: list[str] = []
    total = len(sources)
    lookback_days = settings.collect_lookback_days

    def progress(i: int, message: str) -> None:
        if on_progress:
            on_progress(current=i, total=total, message=message)

    progress(0, f"准备采集 {total} 个新闻源（近 {lookback_days} 天）…")

    for index, source in enumerate(sources, start=1):
        progress(index - 1, f"采集中 ({index}/{total})：{source.name}")
        try:
            result = collector.collect_source(source)
        except Exception as exc:  # noqa: BLE001 — keep other sources running
            session.rollback()
            SourceRepository(session).mark_error(source, "COLLECT_ERROR")
            errors.append(f"{source.name}: {exc}")
            progress(index, f"失败：{source.name}")
            continue

        if not result.ok:
            SourceRepository(session).mark_error(source, result.error_code or "UNKNOWN_ERROR")
            errors.append(f"{source.name}: {result.error_code}")
            progress(index, f"失败：{source.name} ({result.error_code})")
            continue

        SourceRepository(session).mark_success(source)
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
                continue
            found += 1
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
                    else:
                        updated += 1
            except (SQLAlchemyError, ValueError, TypeError) as exc:
                skipped += 1
                errors.append(f"{source.name}/{label}: {exc.__class__.__name__}")
                continue
        # Commit per source so UI can see partial data if refreshed mid-run.
        try:
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            errors.append(f"{source.name}: commit failed ({exc.__class__.__name__})")
            progress(index, f"提交失败：{source.name}")
            continue
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
    progress(total, f"新闻采集结束：新建 {created}，更新 {updated}，跳过 {skipped}")
    return {
        "run_id": str(run.id),
        "status": status,
        "items_found": found,
        "items_created": created,
        "items_updated": updated,
        "items_skipped": skipped,
        "errors": errors,
    }
