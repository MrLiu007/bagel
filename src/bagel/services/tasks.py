"""In-memory manual collect task runner with progress reporting.

Powers `/collect` — runs jobs in background threads, persists recent task
state under `data/task_state.json`, and survives process restart by marking
in-flight tasks failed.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from bagel.settings import get_settings
from bagel.storage.database import get_engine, get_session_factory


ProgressCallback = Callable[..., None]


@dataclass
class TaskState:
    id: str
    kind: str
    status: str = "pending"  # pending | running | success | failed
    current: int = 0
    total: int = 0
    percent: float = 0.0
    message: str = "等待开始"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskManager:
    _PERSIST_LIMIT = 50

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskState] = {}
        self._running_kinds: set[str] = set()
        self._load_from_disk()

    def _tasks_path(self) -> Path:
        return Path(get_settings().data_dir) / "task_state.json"

    def _load_from_disk(self) -> None:
        path = self._tasks_path()
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for raw in payload.get("tasks", []):
            try:
                state = TaskState(**raw)
            except TypeError:
                continue
            if state.status in {"pending", "running"}:
                state.status = "failed"
                state.message = "已中断"
                state.error = "服务重启后任务中断，请重新发起"
                state.finished_at = datetime.now(UTC).isoformat()
            self._tasks[state.id] = state

    def _persist(self) -> None:
        path = self._tasks_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                items = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
            payload = {"tasks": [asdict(t) for t in items[: self._PERSIST_LIMIT]]}
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def get(self, task_id: str) -> TaskState | None:
        with self._lock:
            state = self._tasks.get(task_id)
            return TaskState(**asdict(state)) if state else None

    def latest(self, kind: str | None = None) -> TaskState | None:
        with self._lock:
            items = list(self._tasks.values())
        if kind:
            items = [t for t in items if t.kind == kind]
        if not items:
            return None
        items.sort(key=lambda t: t.created_at, reverse=True)
        return TaskState(**asdict(items[0]))

    def list_recent(self, limit: int = 10) -> list[TaskState]:
        with self._lock:
            items = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
            return [TaskState(**asdict(t)) for t in items[:limit]]

    def _update(self, task_id: str, **kwargs: Any) -> None:
        with self._lock:
            state = self._tasks[task_id]
            explicit_percent = kwargs.pop("percent", None)
            for key, value in kwargs.items():
                setattr(state, key, value)
            if explicit_percent is not None:
                state.percent = round(float(explicit_percent), 1)
            elif state.total > 0:
                state.percent = round(100.0 * min(state.current, state.total) / state.total, 1)
            else:
                state.percent = 0.0 if state.status != "success" else 100.0
        self._persist()

    def start(self, kind: str, *, options: dict[str, Any] | None = None) -> TaskState:
        options = options or {}
        with self._lock:
            if kind in self._running_kinds or any(
                t.status == "running" and t.kind == kind for t in self._tasks.values()
            ):
                running = next(
                    (t for t in self._tasks.values() if t.status == "running" and t.kind == kind),
                    None,
                )
                if running:
                    return TaskState(**asdict(running))
            task_id = uuid.uuid4().hex
            state = TaskState(id=task_id, kind=kind, status="pending", message="排队中")
            self._tasks[task_id] = state
            self._running_kinds.add(kind)
        self._persist()

        thread = threading.Thread(
            target=self._run,
            args=(task_id, kind, options),
            name=f"task-{kind}-{task_id[:8]}",
            daemon=True,
        )
        thread.start()
        return self.get(task_id)  # type: ignore[return-value]

    def _run(self, task_id: str, kind: str, options: dict[str, Any]) -> None:
        self._update(task_id, status="running", message="启动中…", current=0, total=0)
        get_settings.cache_clear()
        import bagel.storage.database as dbmod

        dbmod._engine = None
        dbmod._SessionLocal = None
        get_engine()
        factory = get_session_factory()
        session = factory()

        def on_progress(*, current: int, total: int, message: str, **extra: Any) -> None:
            payload: dict[str, Any] = {
                "current": current,
                "total": max(total, 0),
                "message": message,
                "status": "running",
            }
            if "percent" in extra and extra["percent"] is not None:
                payload["percent"] = extra["percent"]
            self._update(task_id, **payload)

        try:
            from bagel.jobs.digest import run_build_digest, run_summarize_selected
            from bagel.jobs.github import run_collect_github
            from bagel.jobs.media import run_collect_media
            from bagel.jobs.monthly_brief import run_build_monthly_briefs
            from bagel.jobs.news import run_collect_news
            from bagel.jobs.papers import run_collect_papers
            from bagel.jobs.stocks import run_collect_stocks

            if kind == "collect_news":
                result = run_collect_news(
                    session,
                    on_progress=on_progress,
                    cn_only=bool(options.get("cn_only")),
                )
            elif kind == "collect_github":
                result = run_collect_github(session, on_progress=on_progress)
            elif kind == "collect_papers":
                result = run_collect_papers(session, on_progress=on_progress)
            elif kind == "collect_stocks":
                result = run_collect_stocks(
                    session,
                    on_progress=on_progress,
                    cn_only=bool(options.get("cn_only")),
                    owner_id=options.get("owner_id"),
                )
            elif kind == "enrich_stocks":
                from bagel.jobs.stock_enrich import run_enrich_stocks

                result = run_enrich_stocks(session, on_progress=on_progress)
            elif kind == "collect_media":
                result = run_collect_media(
                    session,
                    platforms=options.get("platforms"),
                    keywords=options.get("keywords"),
                    owner_id=options.get("owner_id"),
                    on_progress=on_progress,
                )
            elif kind == "summarize":
                result = run_summarize_selected(session, on_progress=on_progress)
            elif kind == "build_digest":
                on_progress(current=0, total=1, message="生成日报…")
                result = run_build_digest(session)
                on_progress(current=1, total=1, message="日报完成")
            elif kind == "build_monthly_briefs":
                result = run_build_monthly_briefs(
                    session,
                    year_month=options.get("year_month"),
                    on_progress=on_progress,
                )
            elif kind == "collect_all":
                on_progress(current=0, total=2, message="采集新闻…")
                news = run_collect_news(
                    session,
                    on_progress=lambda **kw: on_progress(
                        current=0,
                        total=2,
                        message=f"新闻：{kw.get('message', '')}",
                    ),
                    cn_only=bool(options.get("cn_only")),
                )
                session.commit()
                on_progress(current=1, total=2, message="采集 GitHub…")
                github = run_collect_github(
                    session,
                    on_progress=lambda **kw: on_progress(
                        current=1,
                        total=2,
                        message=f"GitHub：{kw.get('message', '')}",
                    ),
                )
                result = {
                    "news": news,
                    "github": github,
                    "items_created": int(news.get("items_created", 0))
                    + int(github.get("items_created", 0)),
                    "items_found": int(news.get("items_found", 0))
                    + int(github.get("items_found", 0)),
                }
                on_progress(current=2, total=2, message="全部采集完成")
            else:
                raise ValueError(f"未知任务类型: {kind}")

            session.commit()
            result_status = str((result or {}).get("status") or "SUCCESS").upper()
            skipped = int((result or {}).get("items_skipped") or 0)
            created = int((result or {}).get("items_created") or 0)
            updated = int((result or {}).get("items_updated") or 0)
            errors = (result or {}).get("errors") or []
            if not isinstance(errors, list):
                errors = [str(errors)]

            def _err_text(*fallbacks: str) -> str:
                for key in ("error", "hint"):
                    val = (result or {}).get(key)
                    if val:
                        return str(val)[:500]
                if errors:
                    return "; ".join(str(e) for e in errors[:5])[:500]
                for fb in fallbacks:
                    if fb:
                        return fb[:500]
                return "任务失败"

            if result_status in {"FAILED", "ERROR"}:
                self._update(
                    task_id,
                    status="failed",
                    message="失败",
                    error=_err_text("任务失败"),
                    result=result,
                    finished_at=datetime.now(UTC).isoformat(),
                    percent=100.0,
                )
                return
            # Guard: never mark green success when nothing was ingested.
            found = int((result or {}).get("items_found") or 0)
            if found <= 0 and created <= 0 and updated <= 0:
                self._update(
                    task_id,
                    status="failed",
                    message="失败（0 条）",
                    error=_err_text("未抓取到任何内容"),
                    result=result,
                    finished_at=datetime.now(UTC).isoformat(),
                    percent=100.0,
                )
                return
            msg = "完成"
            extra_error = None
            if result_status == "PARTIAL" or skipped:
                failed = (result or {}).get("platforms_failed") or []
                if failed:
                    labels = "、".join(
                        str(f.get("label") or f.get("platform") or "")
                        for f in failed
                        if isinstance(f, dict)
                    )
                    msg = f"部分完成（新建 {created}，更新 {updated}；已跳过 {labels}）"
                else:
                    msg = f"部分完成（新建 {created}，跳过 {skipped}）"
                hint = (result or {}).get("hint")
                if hint:
                    extra_error = str(hint)[:500]
            elif updated or created:
                msg = f"完成（新建 {created}，更新 {updated}）"
            with self._lock:
                total = self._tasks[task_id].total or self._tasks[task_id].current
            self._update(
                task_id,
                status="success",
                message=msg,
                result=result,
                error=extra_error,
                finished_at=datetime.now(UTC).isoformat(),
                percent=100.0,
                current=total,
            )
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("task.failed id=%s kind=%s", task_id, kind)
            session.rollback()
            self._update(
                task_id,
                status="failed",
                message="失败",
                error=str(exc)[:500],
                finished_at=datetime.now(UTC).isoformat(),
            )
        finally:
            session.close()
            with self._lock:
                self._running_kinds.discard(kind)


task_manager = TaskManager()
