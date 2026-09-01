"""Jobs for LLM summarization and digest generation."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, JobStatus
from bagel.services.digest import write_daily_digest
from bagel.services.llm import LlmClient
from bagel.settings import Settings, get_settings
from bagel.storage.repositories import ItemRepository, JobRunRepository


def run_summarize_selected(
    session: Session,
    settings: Settings | None = None,
    *,
    on_progress: Callable[..., None] | None = None,
) -> dict:
    settings = settings or get_settings()
    jobs = JobRunRepository(session)
    run = jobs.start("summarize_selected")
    client = LlmClient(settings)
    repo = ItemRepository(session)

    items = list(repo.list_by_status(ItemStatus.SELECTED, limit=50))
    found = updated = 0
    errors: list[str] = []

    if not client.available:
        jobs.finish(
            run,
            status=JobStatus.PARTIAL,
            items_found=len(items),
            error_code="LLM_DISABLED",
            error_message="LLM not configured; skip summarization",
        )
        return {
            "run_id": str(run.id),
            "status": JobStatus.PARTIAL,
            "items_found": len(items),
            "items_updated": 0,
            "errors": ["LLM not configured"],
        }

    for idx, item in enumerate(items, start=1):
        found += 1
        if on_progress:
            on_progress(current=idx - 1, total=len(items), message=f"摘要中：{item.title[:40]}")
        result = client.summarize_item(item)
        if not result.ok:
            errors.append(f"{item.id}: {result.error_code}")
            continue
        # Never overwrite raw evidence / original title / url.
        item.llm_summary = result.summary
        item.llm_why = result.why
        item.llm_audience = result.audience
        item.llm_title_zh = result.title_zh
        item.status = ItemStatus.SUMMARIZED
        session.flush()
        updated += 1

    status = JobStatus.SUCCESS
    error_code = None
    error_message = None
    if errors and updated > 0:
        status = JobStatus.PARTIAL
        error_message = "; ".join(errors[:10])
    elif errors and updated == 0:
        status = JobStatus.FAILED
        error_code = "LLM_ERRORS"
        error_message = "; ".join(errors[:10])

    jobs.finish(
        run,
        status=status,
        items_found=found,
        items_updated=updated,
        error_code=error_code,
        error_message=error_message,
    )
    return {
        "run_id": str(run.id),
        "status": status,
        "items_found": found,
        "items_updated": updated,
        "errors": errors,
    }


def run_build_digest(session: Session, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    jobs = JobRunRepository(session)
    run = jobs.start("build_digest")
    try:
        bundle = write_daily_digest(session, settings)
        jobs.finish(
            run,
            status=JobStatus.SUCCESS,
            items_found=bundle.item_count,
            items_created=1,
        )
        return {
            "run_id": str(run.id),
            "status": JobStatus.SUCCESS,
            "path_md": str(bundle.path_md),
            "path_html": str(bundle.path_html),
            "item_count": bundle.item_count,
            "markdown": bundle.markdown,
        }
    except Exception as exc:  # noqa: BLE001 — job boundary
        jobs.finish(
            run,
            status=JobStatus.FAILED,
            error_code="DIGEST_ERROR",
            error_message=str(exc)[:500],
        )
        return {
            "run_id": str(run.id),
            "status": JobStatus.FAILED,
            "errors": [str(exc)],
        }
