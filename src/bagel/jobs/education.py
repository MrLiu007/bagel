"""Job: collect open education resources from configured EDUCATION sources."""

from __future__ import annotations

import time
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.collectors.education import fetch_from_source
from bagel.domain.enums import ItemStatus, ItemType, KeywordScope, SourceType
from bagel.domain.models import IntelSource
from bagel.jobs.metrics import elapsed_ms, source_stat
from bagel.pipeline.category import classify_title
from bagel.pipeline.filter import apply_keyword_rules
from bagel.pipeline.keyword_scopes import rules_for_scope
from bagel.services import wiki as wiki_svc
from bagel.settings import get_settings
from bagel.storage.repositories import ItemRepository, KeywordRuleRepository

ProgressCallback = Callable[..., None]


def run_collect_education(
    session: Session,
    *,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    job_t0 = time.perf_counter()
    sources = list(
        session.scalars(
            select(IntelSource)
            .where(
                IntelSource.source_type == SourceType.EDUCATION,
                IntelSource.enabled.is_(True),
            )
            .order_by(IntelSource.priority)
        ).all()
    )
    if not sources:
        return {
            "status": "FAILED",
            "error": "未配置教育数据源：请在系统设置 → 教育数据源中添加",
            "items_created": 0,
            "items_found": 0,
            "duration_ms": 0,
            "source_stats": [],
        }

    repo = ItemRepository(session)
    settings = get_settings()
    rules = rules_for_scope(
        KeywordRuleRepository(session).list_enabled(),
        KeywordScope.EDUCATION,
    )
    created = 0
    found = 0
    errors: list[str] = []
    source_stats: list[dict[str, Any]] = []

    for i, src in enumerate(sources, start=1):
        src_t0 = time.perf_counter()
        src_created = 0
        if on_progress:
            on_progress(current=i - 1, total=len(sources), message=f"拉取 {src.name}")
        try:
            records = fetch_from_source(src.name, src.url)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{src.name}: {exc}"[:200])
            src.last_error_code = "FETCH_ERROR"
            source_stats.append(
                source_stat(
                    src.name,
                    status="failed",
                    source_id=str(src.id),
                    duration_ms=elapsed_ms(src_t0),
                    error=str(exc),
                )
            )
            continue

        found += len(records)
        for rec in records:
            filt = apply_keyword_rules(rec.title, rec.summary, rules)
            status = filt.status if filt.accepted else ItemStatus.REJECTED
            tags = list(
                {
                    rec.institution,
                    *(rec.tags or []),
                    *filt.matched_include,
                    *filt.matched_boost,
                }
            )[:12]
            item, was_created = repo.upsert_from_normalized(
                item_type=ItemType.EDUCATION,
                source_type=SourceType.EDUCATION,
                source_id=src.id,
                title=rec.title[:500],
                url=rec.url,
                summary=rec.summary,
                author=rec.authors or None,
                published_at=rec.published_at,
                tags=tags,
                category=classify_title(rec.title, rec.summary or ""),
                metadata={
                    "external_id": rec.external_id,
                    "institution": rec.institution,
                    "education": True,
                    "filter": {
                        "include": filt.matched_include,
                        "exclude": filt.matched_exclude,
                        "boost": filt.matched_boost,
                    },
                },
                status=status,
                score=1.05 + filt.score,
            )
            if was_created:
                created += 1
                src_created += 1
                if not item.llm_why:
                    item.llm_why = (
                        "教育启发：该开放课程/资源能否转化为教学内容或自学路径？"
                        "适合哪类学习者与前置知识？"
                    )
                wiki_svc.export_item(item, settings)
        src.last_error_code = None
        source_stats.append(
            source_stat(
                src.name,
                status="success",
                source_id=str(src.id),
                items_found=len(records),
                items_created=src_created,
                items_updated=len(records) - src_created,
                duration_ms=elapsed_ms(src_t0),
            )
        )

    if on_progress:
        on_progress(current=len(sources), total=len(sources), message=f"完成，新建 {created}")

    status = "SUCCESS"
    if errors and created == 0:
        status = "FAILED"
    elif errors:
        status = "PARTIAL"
    return {
        "status": status,
        "items_found": found,
        "items_created": created,
        "sources": len(sources),
        "duration_ms": elapsed_ms(job_t0),
        "source_stats": source_stats,
        "errors": errors[:8],
    }
