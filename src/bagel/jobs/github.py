"""GitHub collection job — queries, releases, and star snapshots."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bagel.collectors.github import COLLECTOR_VERSION, GithubCollector
from bagel.domain.enums import ItemStatus, JobStatus, KeywordScope
from bagel.jobs.metrics import elapsed_ms, source_stat
from bagel.pipeline.category import classify_title
from bagel.pipeline.filter import apply_keyword_rules
from bagel.pipeline.keyword_scopes import rules_for_scope
from bagel.pipeline.recency import (
    github_query_with_recency,
    is_within_lookback,
    sort_key_published,
)
from bagel.pipeline.textutil import strip_html, truncate
from bagel.settings import Settings, get_settings
from bagel.storage.repositories import (
    GithubQueryRepository,
    GithubSnapshotRepository,
    ItemRepository,
    JobRunRepository,
    KeywordRuleRepository,
    RawEvidenceRepository,
)

logger = logging.getLogger(__name__)
ProgressCallback = Callable[..., None]


def _item_label(title: str | None, url: str | None) -> str:
    label = (title or url or "unknown").strip()
    return label[:80] + ("…" if len(label) > 80 else "")


def _result_hint(errors: list[str], *, found: int, created: int) -> str | None:
    if errors:
        return "; ".join(errors[:8])
    if found <= 0 and created <= 0:
        return "未抓取到任何内容（请检查 GitHub Query、网络/代理或 GITHUB_TOKEN）"
    return None


def run_collect_github(
    session: Session,
    settings: Settings | None = None,
    *,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    jobs = JobRunRepository(session)
    run = jobs.start("collect_github")

    def progress(current: int, total: int, message: str) -> None:
        if on_progress:
            on_progress(current=current, total=total, message=message)

    if not settings.enable_github:
        jobs.finish(
            run,
            status=JobStatus.SUCCESS,
            error_message="GitHub collection disabled",
        )
        progress(1, 1, "GitHub 采集已关闭")
        return {
            "run_id": str(run.id),
            "status": JobStatus.SUCCESS,
            "items_found": 0,
            "items_created": 0,
            "items_updated": 0,
            "items_skipped": 0,
            "duration_ms": 0,
            "source_stats": [],
            "errors": ["GitHub collection disabled"],
            "hint": "ENABLE_GITHUB=false",
        }

    query_repo = GithubQueryRepository(session)
    queries = list(query_repo.list_enabled())
    rules = rules_for_scope(
        KeywordRuleRepository(session).list_enabled(),
        KeywordScope.GITHUB,
    )
    collector = GithubCollector(settings)
    items_repo = ItemRepository(session)
    evidence_repo = RawEvidenceRepository(session)
    snapshots_repo = GithubSnapshotRepository(session)

    found = created = updated = skipped = 0
    errors: list[str] = []
    source_stats: list[dict[str, Any]] = []
    seen_repos: set[str] = set()
    total = len(queries)
    lookback_days = settings.collect_lookback_days
    job_t0 = time.perf_counter()
    logger.info(
        "collect_github.start queries=%s lookback_days=%s token=%s proxy=%s",
        total,
        lookback_days,
        bool(settings.github_token),
        bool(settings.proxy_url),
    )

    if total == 0:
        hint = "没有启用的 GitHub Query，请在系统设置中添加"
        logger.warning("collect_github.empty_queries")
        jobs.finish(run, status=JobStatus.FAILED, error_code="NO_QUERIES", error_message=hint)
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
        progress(1, 1, hint)
        return {
            "run_id": str(run.id),
            "status": JobStatus.FAILED,
            "items_found": 0,
            "items_created": 0,
            "items_updated": 0,
            "items_skipped": 0,
            "duration_ms": elapsed_ms(job_t0),
            "source_stats": [],
            "errors": [hint],
            "error": hint,
            "hint": hint,
        }

    progress(0, total, f"准备执行 {total} 组 GitHub Query（近 {lookback_days} 天）…")

    for index, query in enumerate(queries, start=1):
        src_t0 = time.perf_counter()
        src_found = src_created = src_updated = src_skipped = 0
        progress(index - 1, total, f"查询中 ({index}/{total})：{query.name}")
        recent_q = github_query_with_recency(query.query, days=lookback_days)
        logger.info("collect_github.query name=%s q=%s", query.name, recent_q)
        try:
            result = collector.search_repos(query, query_override=recent_q)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            query_repo.mark_run(query, result_count=0, error=str(exc)[:200])
            errors.append(f"{query.name}: {exc}")
            logger.exception("collect_github.query_exception name=%s", query.name)
            source_stats.append(
                source_stat(
                    query.name,
                    status="failed",
                    duration_ms=elapsed_ms(src_t0),
                    error=str(exc),
                )
            )
            progress(index, total, f"失败：{query.name}")
            continue

        if not result.ok:
            detail = result.error_message or result.error_code or "unknown"
            query_repo.mark_run(query, result_count=0, error=str(result.error_code))
            errors.append(f"{query.name}: {result.error_code} ({detail})")
            logger.warning(
                "collect_github.query_failed name=%s code=%s http=%s detail=%s",
                query.name,
                result.error_code,
                result.http_status,
                detail[:200],
            )
            source_stats.append(
                source_stat(
                    query.name,
                    status="failed",
                    duration_ms=elapsed_ms(src_t0),
                    error=f"{result.error_code} ({detail})",
                )
            )
            progress(index, total, f"失败：{query.name} ({result.error_code})")
            continue

        query_repo.mark_run(query, result_count=result.result_count, error=None)
        logger.info(
            "collect_github.query_ok name=%s api_count=%s items=%s",
            query.name,
            result.result_count,
            len(result.items),
        )

        for snap in result.snapshots:
            name = snap.get("repo_full_name")
            if not name:
                continue
            try:
                with session.begin_nested():
                    snapshots_repo.record(
                        repo_full_name=name,
                        stars=int(snap.get("stars") or 0),
                        forks=int(snap.get("forks") or 0),
                        open_issues=int(snap.get("open_issues") or 0),
                    )
                seen_repos.add(name)
            except SQLAlchemyError:
                continue

        repo_items = sorted(
            result.items,
            key=lambda n: sort_key_published(n.published_at),
            reverse=True,
        )
        for normalized in repo_items:
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
                        source_url=normalized.url,
                        external_id=normalized.external_id,
                        raw_payload=normalized.raw_payload,
                        http_status=normalized.http_status,
                        etag=normalized.etag,
                        last_modified=normalized.last_modified,
                        collector_version=COLLECTOR_VERSION,
                    )
                    meta = dict(normalized.metadata or {})
                    repo_name = meta.get("repo_full_name")
                    if repo_name:
                        delta = snapshots_repo.star_delta(repo_name, days=7)
                        if delta is not None and delta > 0:
                            meta["star_delta_7d"] = delta
                            meta["change_type"] = meta.get("change_type") or "STAR_GROWTH"
                    meta["filter"] = {
                        "include": filt.matched_include,
                        "exclude": filt.matched_exclude,
                        "boost": filt.matched_boost,
                    }
                    summary = truncate(normalized.summary or normalized.content, 400) or None
                    category = classify_title(normalized.title, summary)
                    tags = list(
                        {*(normalized.tags or []), *filt.matched_include, *filt.matched_boost}
                    )
                    status = filt.status if filt.accepted else ItemStatus.REJECTED
                    score = float(meta.get("stars") or 0) / 1000.0 + filt.score

                    _item, was_created = items_repo.upsert_from_normalized(
                        item_type=normalized.item_type,
                        source_type=normalized.source_type,
                        source_id=None,
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
                        metadata=meta,
                        raw_evidence_id=evidence.id,
                        status=status,
                        score=score,
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
                errors.append(f"{query.name}/{label}: {exc.__class__.__name__}")
                logger.warning(
                    "collect_github.item_skip name=%s item=%s err=%s",
                    query.name,
                    label,
                    exc,
                )
                continue

        try:
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            errors.append(f"{query.name}: commit failed ({exc.__class__.__name__})")
            logger.exception("collect_github.commit_failed name=%s", query.name)
            source_stats.append(
                source_stat(
                    query.name,
                    status="failed",
                    items_found=src_found,
                    items_created=src_created,
                    items_updated=src_updated,
                    items_skipped=src_skipped,
                    duration_ms=elapsed_ms(src_t0),
                    error=f"commit failed ({exc.__class__.__name__})",
                )
            )
            progress(index, total, f"提交失败：{query.name}")
            continue
        source_stats.append(
            source_stat(
                query.name,
                status="success",
                items_found=src_found,
                items_created=src_created,
                items_updated=src_updated,
                items_skipped=src_skipped,
                duration_ms=elapsed_ms(src_t0),
            )
        )
        progress(index, total, f"完成：{query.name}（累计新建 {created}，跳过 {skipped}）")

    release_targets = list(seen_repos)[:5]
    for offset, repo_name in enumerate(release_targets, start=1):
        src_t0 = time.perf_counter()
        progress(total + offset - 1, total + len(release_targets), f"Release：{repo_name}")
        try:
            release = collector.fetch_latest_release(repo_name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"release/{repo_name}: {exc}")
            logger.warning("collect_github.release_exception repo=%s err=%s", repo_name, exc)
            source_stats.append(
                source_stat(
                    f"release/{repo_name}",
                    status="failed",
                    duration_ms=elapsed_ms(src_t0),
                    error=str(exc),
                )
            )
            continue
        if not release:
            # Many trending repos never publish GitHub Releases — skip quietly.
            logger.debug("collect_github.no_release repo=%s", repo_name)
            continue
        if not is_within_lookback(release.published_at, days=lookback_days, keep_unknown=False):
            logger.debug("collect_github.release_outside_lookback repo=%s", repo_name)
            continue
        found += 1
        label = _item_label(release.title, release.url)
        try:
            with session.begin_nested():
                evidence = evidence_repo.create(
                    source_type=release.source_type,
                    source_url=release.url,
                    external_id=release.external_id,
                    raw_payload=release.raw_payload,
                    collector_version=COLLECTOR_VERSION,
                )
                summary = truncate(release.summary or release.content, 400) or None
                category = classify_title(release.title, summary)
                _item, was_created = items_repo.upsert_from_normalized(
                    item_type=release.item_type,
                    source_type=release.source_type,
                    source_id=None,
                    title=strip_html(release.title) or release.title,
                    url=release.url,
                    summary=summary,
                    content=release.content,
                    author=release.author,
                    published_at=release.published_at,
                    tags=list(release.tags or []),
                    topics=list({*(release.topics or []), category}),
                    category=category,
                    metadata=dict(release.metadata or {}),
                    raw_evidence_id=evidence.id,
                    status=ItemStatus.CANDIDATE,
                    score=1.0,
                )
                if was_created:
                    created += 1
                    src_created = 1
                    src_updated = 0
                else:
                    updated += 1
                    src_created = 0
                    src_updated = 1
            session.commit()
            source_stats.append(
                source_stat(
                    f"release/{repo_name}",
                    status="success",
                    items_found=1,
                    items_created=src_created,
                    items_updated=src_updated,
                    duration_ms=elapsed_ms(src_t0),
                )
            )
        except (SQLAlchemyError, ValueError, TypeError) as exc:
            session.rollback()
            skipped += 1
            errors.append(f"release/{label}: {exc.__class__.__name__}")
            source_stats.append(
                source_stat(
                    f"release/{repo_name}",
                    status="failed",
                    duration_ms=elapsed_ms(src_t0),
                    error=exc.__class__.__name__,
                )
            )
            continue

    status = JobStatus.SUCCESS
    error_code = None
    error_message = None
    if errors and (created + updated) > 0:
        status = JobStatus.PARTIAL
        error_message = "; ".join(errors[:10])
    elif errors and (created + updated) == 0:
        status = JobStatus.FAILED
        error_message = "; ".join(errors[:10])
        error_code = "GITHUB_COLLECT_ERRORS"

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
    final_total = total + len(release_targets)
    hint = _result_hint(errors, found=found, created=created)
    logger.info(
        "collect_github.done status=%s found=%s created=%s updated=%s skipped=%s errors=%s",
        status,
        found,
        created,
        updated,
        skipped,
        len(errors),
    )
    if errors:
        logger.warning("collect_github.errors %s", "; ".join(errors[:10]))
    progress(final_total, final_total, f"GitHub 采集结束：新建 {created}，更新 {updated}，跳过 {skipped}")
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
    }
