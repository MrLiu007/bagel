"""Job: collect academic papers from configured PAPER sources."""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.collectors.papers import fetch_from_source
from bagel.domain.enums import ItemStatus, ItemType, SourceType
from bagel.domain.models import IntelSource
from bagel.pipeline.category import classify_title
from bagel.services import wiki as wiki_svc
from bagel.settings import get_settings
from bagel.storage.repositories import ItemRepository

ProgressCallback = Callable[..., None]


def run_collect_papers(
    session: Session,
    *,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
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
        }

    repo = ItemRepository(session)
    settings = get_settings()
    created = 0
    found = 0
    errors: list[str] = []

    for i, src in enumerate(sources, start=1):
        if on_progress:
            on_progress(current=i - 1, total=len(sources), message=f"拉取 {src.name}")
        try:
            papers = fetch_from_source(src.name, src.url)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{src.name}: {exc}"[:200])
            src.last_error_code = "FETCH_ERROR"
            continue

        found += len(papers)
        for paper in papers:
            item, was_created = repo.upsert_from_normalized(
                item_type=ItemType.PAPER,
                source_type=SourceType.PAPER,
                source_id=src.id,
                title=paper.title[:500],
                url=paper.url,
                summary=paper.summary,
                author=paper.authors or None,
                published_at=paper.published_at,
                tags=[paper.source_name, paper.venue][:8],
                category=classify_title(paper.title, paper.summary or ""),
                metadata={
                    "external_id": paper.external_id,
                    "venue": paper.venue,
                    "science": True,
                },
                status=ItemStatus.CANDIDATE,
                score=1.1,
            )
            if was_created:
                created += 1
                if not item.llm_why:
                    item.llm_why = (
                        "科普落脚：该工作的核心思想能否转化为教学项目或课程案例？"
                        "是否有助于降低学员理解前沿技术的门槛？"
                    )
                wiki_svc.export_item(item, settings)
        src.last_error_code = None

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
        "errors": errors[:8],
    }
