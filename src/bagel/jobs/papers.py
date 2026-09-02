"""Job: collect academic papers from configured PAPER sources."""

from __future__ import annotations

import time
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.collectors.papers import fetch_from_source
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


def run_collect_papers(
    session: Session,
    *,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    job_t0 = time.perf_counter()
    sources = list(
        session.scalars(
            select(IntelSource)
            .where(
                IntelSource.source_type == SourceType.PAPER,
                IntelSource.enabled.is_(True),
            )
            .order_by(IntelSource.priority)
        ).all()
    )
    if not sources:
        return {
            "status": "FAILED",
            "error": "未配置论文数据源：请在系统设置 → 论文数据源中添加",
            "items_created": 0,
            "items_found": 0,
            "duration_ms": 0,
            "source_stats": [],
        }

    repo = ItemRepository(session)
    settings = get_settings()
    rules = rules_for_scope(
        KeywordRuleRepository(session).list_enabled(),
        KeywordScope.PAPERS,
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
            papers = fetch_from_source(src.name, src.url)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            rate_limited = "429" in msg or "Too Many Requests" in msg
            code = "RATE_LIMITED" if rate_limited else "FETCH_ERROR"
            hint = (
                "Semantic Scholar 限流（429）。可在 .env 设置 SEMANTIC_SCHOLAR_API_KEY，"
                "或暂时关闭该论文源。"
                if rate_limited
                else msg
            )
            errors.append(f"{src.name}: {hint}"[:220])
            src.last_error_code = code
            source_stats.append(
                source_stat(
                    src.name,
                    status="rate_limited" if rate_limited else "failed",
                    source_id=str(src.id),
                    duration_ms=elapsed_ms(src_t0),
                    error=hint,
                )
            )
            continue

        found += len(papers)
        for paper in papers:
            filt = apply_keyword_rules(paper.title, paper.summary, rules)
            status = filt.status if filt.accepted else ItemStatus.REJECTED
            item, was_created = repo.upsert_from_normalized(
                item_type=ItemType.PAPER,
                source_type=SourceType.PAPER,
                source_id=src.id,
                title=paper.title[:500],
                url=paper.url,
                summary=paper.summary,
                author=paper.authors or None,
                published_at=paper.published_at,
                tags=list({paper.source_name, paper.venue, *filt.matched_include, *filt.matched_boost})[:12],
                category=classify_title(paper.title, paper.summary or ""),
                metadata={
                    "external_id": paper.external_id,
                    "venue": paper.venue,
                    "science": True,
                    "filter": {
                        "include": filt.matched_include,
                        "exclude": filt.matched_exclude,
                        "boost": filt.matched_boost,
                    },
                },
                status=status,
                score=1.1 + filt.score,
            )
            if was_created:
                created += 1
                src_created += 1
                if not item.llm_why:
                    item.llm_why = (
                        "科普落脚：该工作的核心思想能否转化为教学项目或课程案例？"
                        "是否有助于降低学员理解前沿技术的门槛？"
                    )
                wiki_svc.export_item(item, settings)
        src.last_error_code = None
        source_stats.append(
            source_stat(
                src.name,
                status="success",
                source_id=str(src.id),
                items_found=len(papers),
                items_created=src_created,
                items_updated=len(papers) - src_created,
                duration_ms=elapsed_ms(src_t0),
            )
        )

    if on_progress:
        on_progress(current=len(sources), total=len(sources), message=f"完成，新建 {created}")

    # Single-source failures (e.g. S2 429) must not fail the whole job when others worked.
    any_ok = any(s.get("status") == "success" for s in source_stats)
    status = "SUCCESS"
    if errors and any_ok:
        status = "PARTIAL"
    elif errors and not any_ok:
        status = "FAILED"
    return {
        "status": status,
        "items_found": found,
        "items_created": created,
        "items_updated": max(0, found - created),
        "sources": len(sources),
        "duration_ms": elapsed_ms(job_t0),
        "source_stats": source_stats,
        "errors": errors[:8],
    }
