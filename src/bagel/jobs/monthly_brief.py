"""Jobs for monthly news / github sharing briefs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from bagel.domain.enums import BriefKind, JobStatus
from bagel.services.monthly_brief import parse_year_month, write_monthly_brief
from bagel.settings import Settings, get_settings
from bagel.storage.repositories import JobRunRepository


def run_build_monthly_briefs(
    session: Session,
    settings: Settings | None = None,
    *,
    year_month: str | None = None,
    kinds: list[str] | None = None,
    on_progress: Callable[..., None] | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    jobs = JobRunRepository(session)
    run = jobs.start("build_monthly_briefs")
    ym = parse_year_month(year_month)
    target_kinds = kinds or [
        BriefKind.NEWS,
        BriefKind.GITHUB,
        BriefKind.SCIENCE,
        BriefKind.EDUCATION,
        BriefKind.MODEL,
        BriefKind.MEDIA,
        BriefKind.STOCK,
    ]
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    total = len(target_kinds)
    for idx, kind in enumerate(target_kinds, start=1):
        if on_progress:
            on_progress(current=idx - 1, total=total, message=f"生成 {ym} {kind} 月度总结…")
        try:
            bundle = write_monthly_brief(
                session, kind=kind, year_month=ym, settings=settings
            )
            session.commit()
            results.append(
                {
                    "kind": kind,
                    "year_month": bundle.year_month,
                    "item_count": bundle.item_count,
                    "path_md": str(bundle.path_md),
                    "title": bundle.title,
                }
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            errors.append(f"{kind}: {exc}")

    status = JobStatus.SUCCESS
    if errors and results:
        status = JobStatus.PARTIAL
    elif errors and not results:
        status = JobStatus.FAILED

    jobs.finish(
        run,
        status=status,
        items_found=sum(r["item_count"] for r in results),
        items_created=len(results),
        error_message="; ".join(errors[:5]) if errors else None,
        error_code="BRIEF_ERRORS" if errors and not results else None,
    )
    session.commit()
    if on_progress:
        on_progress(current=total, total=total, message=f"{ym} 月度总结完成")
    return {
        "run_id": str(run.id),
        "status": status,
        "year_month": ym,
        "briefs": results,
        "errors": errors,
    }
