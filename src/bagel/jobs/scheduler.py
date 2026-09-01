"""Lightweight in-process scheduler (no Celery).

Interval = N minutes + random jitter [0, jitter_seconds], via APScheduler IntervalTrigger.jitter.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bagel.services.runtime_config import load_runtime_config
from bagel.settings import Settings, get_settings
from bagel.storage.database import get_session_factory

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _run_job(name: str, fn: Callable) -> None:
    factory = get_session_factory()
    session = factory()
    result: Any = None
    try:
        logger.info("job.start name=%s", name)
        result = fn(session)
        session.commit()
        logger.info("job.done name=%s result=%s", name, result)
        try:
            from bagel.services.feishu_notify import maybe_push_after_collect

            maybe_push_after_collect(name, result)
        except Exception:  # noqa: BLE001
            logger.exception("feishu.notify.hook_failed name=%s", name)
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("job.failed name=%s", name)
    finally:
        session.close()


def scheduler_status() -> dict[str, Any]:
    cfg = load_runtime_config()
    jobs = []
    if _scheduler and _scheduler.running:
        for job in _scheduler.get_jobs():
            nxt = job.next_run_time
            jobs.append(
                {
                    "id": job.id,
                    "next_run_time": nxt.isoformat() if nxt else None,
                }
            )
    return {
        "running": bool(_scheduler and _scheduler.running),
        "enabled": cfg.enable_scheduler,
        "interval_minutes": cfg.schedule_interval_minutes,
        "jitter_seconds": cfg.schedule_jitter_seconds,
        "jobs": jobs,
    }


def start_scheduler(settings: Settings | None = None) -> BackgroundScheduler | None:
    """Start or no-op. Returns None when disabled in runtime config."""
    global _scheduler
    settings = settings or get_settings()
    cfg = load_runtime_config()
    if not cfg.enable_scheduler:
        logger.info("scheduler.skipped reason=disabled")
        return None

    if _scheduler and _scheduler.running:
        reload_scheduler_jobs()
        return _scheduler

    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler = sched
    _register_jobs(sched, settings, cfg)
    sched.start()
    logger.info(
        "scheduler.started interval=%sm jitter=%ss",
        cfg.schedule_interval_minutes,
        cfg.schedule_jitter_seconds,
    )
    return sched


def reload_scheduler_jobs(settings: Settings | None = None) -> dict[str, Any]:
    """Re-apply jobs from runtime config; start/stop as needed."""
    global _scheduler
    settings = settings or get_settings()
    cfg = load_runtime_config()

    if not cfg.enable_scheduler:
        stop_scheduler()
        return scheduler_status()

    if _scheduler is None or not _scheduler.running:
        start_scheduler(settings)
        return scheduler_status()

    for job in list(_scheduler.get_jobs()):
        job.remove()
    _register_jobs(_scheduler, settings, cfg)
    logger.info("scheduler.reloaded")
    return scheduler_status()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler.stopped")
    _scheduler = None


def _register_jobs(sched: BackgroundScheduler, settings: Settings, cfg) -> None:
    from bagel.jobs.digest import run_build_digest, run_summarize_selected
    from bagel.jobs.github import run_collect_github
    from bagel.jobs.news import run_collect_news
    from bagel.jobs.stocks import run_collect_stocks

    minutes = cfg.schedule_interval_minutes
    jitter = cfg.schedule_jitter_seconds
    trigger = IntervalTrigger(minutes=minutes, jitter=jitter)

    if cfg.schedule_collect_news:
        sched.add_job(
            lambda: _run_job("collect_news", run_collect_news),
            trigger,
            id="collect_news",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    if cfg.schedule_collect_github and settings.enable_github:
        sched.add_job(
            lambda: _run_job("collect_github", run_collect_github),
            IntervalTrigger(minutes=minutes, jitter=jitter),
            id="collect_github",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    if cfg.schedule_collect_stocks:
        sched.add_job(
            lambda: _run_job("collect_stocks", run_collect_stocks),
            IntervalTrigger(minutes=minutes, jitter=jitter),
            id="collect_stocks",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    sched.add_job(
        lambda: _run_job("summarize_selected", run_summarize_selected),
        IntervalTrigger(minutes=max(30, minutes), jitter=jitter),
        id="summarize_selected",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        lambda: _run_job("build_digest", run_build_digest),
        CronTrigger(hour=settings.digest_hour, minute=0),
        id="build_digest",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
