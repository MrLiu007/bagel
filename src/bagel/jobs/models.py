"""Job: collect AI models from Hugging Face / ModelScope sources."""

from __future__ import annotations

import time
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.collectors.models import COMMUNITY_LABELS, fetch_from_source
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


def run_collect_models(
    session: Session,
    *,
    on_progress: ProgressCallback | None = None,
    owner_id: Any = None,
) -> dict[str, Any]:
    job_t0 = time.perf_counter()
    oid = None
    if owner_id:
        from uuid import UUID

        oid = owner_id if isinstance(owner_id, UUID) else UUID(str(owner_id))
    sources = list(
        session.scalars(
            select(IntelSource)
            .where(
                IntelSource.source_type == SourceType.MODEL,
                IntelSource.enabled.is_(True),
            )
            .order_by(IntelSource.priority)
        ).all()
    )
    if not sources:
        return {
            "status": "FAILED",
            "error": "未配置模型数据源：请在系统设置 → 模型数据源中添加",
            "items_created": 0,
            "items_found": 0,
            "items_updated": 0,
            "items_skipped": 0,
            "duration_ms": 0,
            "source_stats": [],
        }

    repo = ItemRepository(session)
    settings = get_settings()
    rules = rules_for_scope(
        KeywordRuleRepository(session).list_enabled(),
        KeywordScope.MODELS,
    )
    created = updated = found = skipped = 0
    errors: list[str] = []
    source_stats: list[dict[str, Any]] = []

    for i, src in enumerate(sources, start=1):
        src_t0 = time.perf_counter()
        src_created = src_updated = src_found = src_skipped = 0
        if on_progress:
            on_progress(current=i - 1, total=len(sources), message=f"拉取 {src.name}")
        try:
            models = fetch_from_source(src.name, src.url)
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

        if not models:
            src.last_error_code = "EMPTY"
            source_stats.append(
                source_stat(
                    src.name,
                    status="skipped",
                    source_id=str(src.id),
                    duration_ms=elapsed_ms(src_t0),
                    error="未返回模型",
                )
            )
            continue

        for model in models:
            # Hub list APIs already return a curated/recent window; do not apply
            # news-style publish lookback (popular models often have old lastModified).
            found += 1
            src_found += 1
            community = model.community
            community_label = COMMUNITY_LABELS.get(community, community)
            filt = apply_keyword_rules(model.title, model.summary, rules)
            status = filt.status if filt.accepted else ItemStatus.REJECTED
            tags = list(
                {
                    community,
                    *(model.tags or [])[:8],
                    *([model.pipeline_tag] if model.pipeline_tag else []),
                    *filt.matched_include,
                    *filt.matched_boost,
                }
            )
            summary = model.summary[:2000] if model.summary else None
            category = classify_title(model.title, summary or "")
            item, was_created = repo.upsert_from_normalized(
                item_type=ItemType.MODEL,
                source_type=SourceType.MODEL,
                source_id=src.id,
                title=model.title[:500],
                url=model.url,
                summary=summary,
                author=model.author or None,
                published_at=model.published_at,
                tags=tags[:16],
                category=category,
                metadata={
                    "external_id": model.external_id,
                    "model_id": model.model_id,
                    "community": community,
                    "platform": community,
                    "community_label": community_label,
                    "downloads": model.downloads,
                    "likes": model.likes,
                    "pipeline_tag": model.pipeline_tag,
                    "filter": {
                        "include": filt.matched_include,
                        "exclude": filt.matched_exclude,
                        "boost": filt.matched_boost,
                    },
                },
                status=status,
                score=1.0 + min(model.downloads, 100_000) / 100_000.0 + filt.score,
                owner_id=oid,
            )
            if was_created:
                created += 1
                src_created += 1
                if not item.llm_why:
                    item.llm_why = (
                        "关注该模型相对常见基线的能力增量、许可与部署成本，"
                        "以及是否适合作为课程案例或产品选型候选。"
                    )
                wiki_svc.export_item(item, settings)
            else:
                updated += 1
                src_updated += 1
        src.last_error_code = None
        source_stats.append(
            source_stat(
                src.name,
                status="success",
                source_id=str(src.id),
                items_found=src_found,
                items_created=src_created,
                items_updated=src_updated,
                items_skipped=src_skipped,
                duration_ms=elapsed_ms(src_t0),
            )
        )

    if on_progress:
        on_progress(
            current=len(sources),
            total=len(sources),
            message=f"完成，新建 {created}，更新 {updated}",
        )

    status = "SUCCESS"
    if errors and created == 0 and updated == 0:
        status = "FAILED"
    elif errors:
        status = "PARTIAL"
    return {
        "status": status,
        "items_found": found,
        "items_created": created,
        "items_updated": updated,
        "items_skipped": skipped,
        "sources": len(sources),
        "duration_ms": elapsed_ms(job_t0),
        "source_stats": source_stats,
        "errors": errors[:8],
        "error": "; ".join(errors[:3]) if errors else None,
        "hint": "; ".join(errors[:3]) if errors else None,
    }
