"""Job: collect academic papers from configured PAPER sources."""

from __future__ import annotations

import time
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.collectors.papers import (
    extract_arxiv_id,
    fetch_from_source,
    resolve_pdf_url,
)
from bagel.domain.enums import ItemStatus, ItemType, KeywordScope, SourceType
from bagel.domain.models import IntelSource
from bagel.jobs.metrics import elapsed_ms, source_stat
from bagel.jobs.source_guard import MAX_SOURCE_ATTEMPTS, safe_source_fetch
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
    # After a rate-limit, pause briefly between sources to reduce pressure.
    rate_limit_cooldown = 0.0

    for i, src in enumerate(sources, start=1):
        src_t0 = time.perf_counter()
        src_created = 0
        if rate_limit_cooldown > 0:
            if on_progress:
                on_progress(
                    current=i - 1,
                    total=len(sources),
                    message=f"限流冷却 {rate_limit_cooldown:.0f}s 后继续…",
                )
            time.sleep(rate_limit_cooldown)
            rate_limit_cooldown = 0.0

        def _notify(attempt: int, total: int, message: str) -> None:
            if on_progress:
                on_progress(current=i - 1, total=len(sources), message=message)

        papers, err_info = safe_source_fetch(
            lambda s=src: fetch_from_source(s.name, s.url),
            source_name=src.name,
            max_attempts=MAX_SOURCE_ATTEMPTS,
            on_attempt=_notify,
        )
        if err_info is not None:
            hint = str(err_info["error"])
            status = str(err_info["status"])
            errors.append(f"{src.name}: {hint}"[:220])
            src.last_error_code = status.upper()
            if status == "rate_limited":
                rate_limit_cooldown = 3.0
            source_stats.append(
                source_stat(
                    src.name,
                    status=status,
                    source_id=str(src.id),
                    duration_ms=elapsed_ms(src_t0),
                    error=hint,
                )
            )
            continue

        assert papers is not None
        found += len(papers)
        for paper in papers:
            filt = apply_keyword_rules(paper.title, paper.summary, rules)
            status = filt.status if filt.accepted else ItemStatus.REJECTED
            arxiv_id = extract_arxiv_id(paper.url) or extract_arxiv_id(paper.external_id)
            # Collect path: local resolve only (no Unpaywall/landing HTTP per item).
            # Remote PDF probe belongs to on-demand「探测开放 PDF」.
            pdf_url = resolve_pdf_url(
                page_url=paper.url,
                external_id=paper.external_id,
                raw=paper.raw,
            )
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
                    "arxiv_id": arxiv_id,
                    "pdf_url": pdf_url,
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

    # Single-source failures must not fail the whole job when others worked.
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
