"""Ingest yt-dlp metadata into IntelItem rows; optional download."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, KeywordScope, Region, SourceType
from bagel.domain.models import IntelItem, IntelSource
from bagel.integrations.ytdlp import (
    download_entry,
    extract_playlist,
    extract_subtitles_only,
    parse_av_source_url,
)
from bagel.jobs.metrics import elapsed_ms, source_stat
from bagel.jobs.source_guard import MAX_SOURCE_ATTEMPTS, safe_source_fetch
from bagel.pipeline.category import classify_title
from bagel.pipeline.filter import apply_keyword_rules
from bagel.pipeline.keyword_scopes import rules_for_scope
from bagel.pipeline.recency import is_within_lookback
from bagel.services import wiki as wiki_svc
from bagel.settings import Settings, get_settings
from bagel.storage.repositories import ItemRepository, KeywordRuleRepository

ProgressCallback = Callable[..., None]


def run_collect_av(
    session: Session,
    settings: Settings | None = None,
    *,
    on_progress: ProgressCallback | None = None,
    owner_id: uuid.UUID | str | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not settings.ytdlp_active:
        return {
            "status": "FAILED",
            "error": "未启用音视频采集：请在 .env 设置 ENABLE_YTDLP=true",
            "items_created": 0,
            "items_found": 0,
            "duration_ms": 0,
            "source_stats": [],
        }

    sources = list(
        session.scalars(
            select(IntelSource)
            .where(
                IntelSource.source_type == SourceType.AV,
                IntelSource.enabled.is_(True),
            )
            .order_by(IntelSource.priority)
        ).all()
    )
    if not settings.enable_overseas_sources:
        sources = [s for s in sources if s.region != Region.GLOBAL]
    sources.sort(key=lambda s: (0 if s.region == Region.CN else 1, s.priority, s.name))

    if not sources:
        return {
            "status": "FAILED",
            "error": "未配置音视频数据源：请在系统设置 → 音视频数据源中添加",
            "items_created": 0,
            "items_found": 0,
            "duration_ms": 0,
            "source_stats": [],
        }

    oid: uuid.UUID | None = None
    if owner_id:
        try:
            oid = owner_id if isinstance(owner_id, uuid.UUID) else uuid.UUID(str(owner_id))
        except (TypeError, ValueError):
            oid = None

    repo = ItemRepository(session)
    rules = rules_for_scope(
        KeywordRuleRepository(session).list_enabled(),
        KeywordScope.AV,
    )
    lookback = settings.collect_lookback_days
    created = updated = found = 0
    errors: list[str] = []
    source_stats: list[dict[str, Any]] = []
    job_t0 = time.perf_counter()
    total = len(sources)

    for i, src in enumerate(sources, start=1):
        src_t0 = time.perf_counter()
        src_created = src_updated = 0
        region_tag = "CN" if src.region == Region.CN else "GLOBAL"

        def _notify(attempt: int, _total: int, message: str) -> None:
            if on_progress:
                on_progress(current=i - 1, total=total, message=message)

        if i > 1 and settings.av_scan_sleep_sec > 0:
            time.sleep(min(10, settings.av_scan_sleep_sec))

        def _fetch(s=src):
            platform, _ = parse_av_source_url(s.url or "")
            result = extract_playlist(
                s.url or "",
                settings=settings,
                on_progress=on_progress,
            )
            return platform, result

        fetched, err_info = safe_source_fetch(
            _fetch,
            source_name=src.name,
            max_attempts=MAX_SOURCE_ATTEMPTS,
            on_attempt=_notify,
        )
        if err_info is not None:
            hint = str(err_info["error"])
            status = str(err_info["status"])
            errors.append(f"[{region_tag}] {src.name}: {hint}"[:200])
            src.last_error_code = status.upper()
            source_stats.append(
                source_stat(
                    src.name,
                    status=status,
                    source_id=str(src.id),
                    duration_ms=elapsed_ms(src_t0),
                    error=hint[:120],
                )
            )
            continue

        assert fetched is not None
        platform, result = fetched

        src.last_error_code = None
        found += len(result.entries)
        for entry in result.entries:
            if entry.published_at and not is_within_lookback(
                entry.published_at, days=lookback, keep_unknown=False
            ):
                continue
            summary = (entry.description or "")[:800]
            filt = apply_keyword_rules(entry.title, summary, rules)
            status = filt.status if filt.accepted else ItemStatus.REJECTED
            tags = list(
                {
                    entry.platform,
                    entry.media_kind,
                    src.name,
                    *filt.matched_include,
                    *filt.matched_boost,
                }
            )[:12]
            item, was_created = repo.upsert_from_normalized(
                item_type=ItemType.AV,
                source_type=SourceType.AV,
                source_id=src.id,
                title=entry.title[:500],
                url=entry.url,
                summary=summary,
                author=entry.author,
                published_at=entry.published_at,
                tags=tags,
                category=classify_title(entry.title, summary),
                metadata={
                    "platform": entry.platform or platform,
                    "external_id": entry.external_id,
                    "media_kind": entry.media_kind,
                    "duration_sec": entry.duration_sec,
                    "thumbnail_url": entry.thumbnail_url,
                    "source_name": src.name,
                    "download": {"status": "none"},
                    "filter": {
                        "include": filt.matched_include,
                        "exclude": filt.matched_exclude,
                        "boost": filt.matched_boost,
                    },
                },
                status=status,
                score=1.0 + filt.score,
                owner_id=oid,
            )
            if was_created:
                created += 1
                src_created += 1
                wiki_svc.export_item(item, settings)
            else:
                updated += 1
                src_updated += 1

        source_stats.append(
            source_stat(
                src.name,
                status="success",
                source_id=str(src.id),
                duration_ms=elapsed_ms(src_t0),
                items_found=len(result.entries),
                items_created=src_created,
                items_updated=src_updated,
            )
        )
        session.commit()

    hints: list[str] = []
    auth_failures = sum(1 for e in errors if "登录" in e or "Cookie" in e or "cookies" in e.lower())
    if auth_failures:
        hints.append(
            "部分 B 站源需登录 Cookie。Chrome 打开时会锁库导致复制失败："
            "请关闭 Chrome，或改用已登录 B 站的 Edge（.env：AV_COOKIES_FROM_BROWSER=edge）。"
        )
    if not (created or updated) and errors:
        hints.append("采集仅拉取标题/链接等元数据，不下载音视频文件；下载请在 /av 条目详情中操作。")

    status = "SUCCESS"
    if errors and (created or updated):
        status = "PARTIAL"
    elif errors and not (created or updated):
        status = "FAILED"

    return {
        "status": status,
        "mode": "metadata_only",
        "items_found": found,
        "items_created": created,
        "items_updated": updated,
        "errors": errors,
        "source_stats": source_stats,
        "duration_ms": elapsed_ms(job_t0),
        "error": errors[0] if status == "FAILED" and errors else None,
        "hint": " ".join(hints) if hints else None,
    }


def run_download_av(
    session: Session,
    *,
    item_id: uuid.UUID | str,
    on_progress: ProgressCallback | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    try:
        iid = item_id if isinstance(item_id, uuid.UUID) else uuid.UUID(str(item_id))
    except (TypeError, ValueError) as exc:
        return {"status": "FAILED", "error": "无效条目 ID"}

    item = session.get(IntelItem, iid)
    if not item or item.item_type != ItemType.AV:
        return {"status": "FAILED", "error": "条目不存在或不是音视频类型"}

    if not (item.url or "").strip() or (item.url or "").startswith("ytdlp://"):
        return {"status": "FAILED", "error": "条目缺少可下载 URL"}

    heal_av_local_download(item, settings=settings)
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    dl = meta.get("download") if isinstance(meta.get("download"), dict) else {}
    if dl.get("status") == "done" and dl.get("local_path"):
        return {"status": "SUCCESS", "skipped": True, "download": dl}

    out_root = Path(settings.data_dir) / "av" / "files" / str(item.id)
    if on_progress:
        on_progress(current=5, total=100, message=f"准备下载 {item.title[:40]}…", percent=5.0)

    result = download_entry(
        item.url,
        out_dir=out_root,
        settings=settings,
        item_id=str(item.id),
        on_progress=on_progress,
    )
    meta = dict(meta)
    meta["download"] = {
        "status": result.get("status", "failed"),
        "local_path": result.get("local_path"),
        "format": result.get("format"),
        "file_size_bytes": result.get("file_size_bytes"),
        "subtitle_path": result.get("subtitle_path"),
        "error": result.get("error"),
    }
    item.metadata_ = meta
    session.flush()

    if result.get("status") != "done":
        return {
            "status": "FAILED",
            "error": result.get("error") or "下载失败",
            "download": meta["download"],
        }
    if on_progress:
        on_progress(current=10, total=10, message="下载完成", percent=100.0)
    return {"status": "SUCCESS", "download": meta["download"]}


def heal_av_local_download(
    item: IntelItem,
    *,
    settings: Settings | None = None,
) -> bool:
    """If a media file already exists on disk, mark download metadata as done."""
    from bagel.integrations.ytdlp import find_local_av_media
    from bagel.pipeline.paths import display_path

    settings = settings or get_settings()
    path = find_local_av_media(str(item.id), settings=settings)
    if path is None or not path.is_file():
        return False
    meta = dict(item.metadata_ if isinstance(item.metadata_, dict) else {})
    dl = meta.get("download") if isinstance(meta.get("download"), dict) else {}
    if dl.get("status") == "done" and dl.get("local_path"):
        # Still refresh path if file moved/renamed.
        if Path(str(dl.get("local_path"))).name == path.name:
            return False
    meta["download"] = {
        "status": "done",
        "local_path": display_path(str(path)),
        "format": path.suffix.lstrip(".").lower(),
        "file_size_bytes": path.stat().st_size,
        "error": None,
        "healed": True,
    }
    item.metadata_ = meta
    return True


def run_extract_av_subtitles(
    session: Session,
    *,
    item_id: uuid.UUID | str,
    on_progress: ProgressCallback | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Build transcript: remote CC → local soft-sub → ASR → optional author desc."""
    from bagel.integrations.av_transcript import (
        burned_in_caption_note,
        extract_soft_subtitles,
        probe_media_streams,
        transcribe_local_media,
    )
    from bagel.integrations.ytdlp import (
        extract_subtitles_only,
        fetch_entry_description,
        find_local_av_media,
        _platform_from_url,
    )

    settings = settings or get_settings()
    try:
        iid = item_id if isinstance(item_id, uuid.UUID) else uuid.UUID(str(item_id))
    except (TypeError, ValueError):
        return {"status": "FAILED", "error": "无效条目 ID"}

    item = session.get(IntelItem, iid)
    if not item or item.item_type != ItemType.AV:
        return {"status": "FAILED", "error": "条目不存在或不是音视频类型"}

    if not (item.url or "").strip() or (item.url or "").startswith("ytdlp://"):
        return {"status": "FAILED", "error": "条目缺少可解析 URL"}

    heal_av_local_download(item, settings=settings)

    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    sub = meta.get("subtitle") if isinstance(meta.get("subtitle"), dict) else {}
    if sub.get("status") == "done" and (item.content or sub.get("text_preview") or "").strip():
        # Allow re-run when prior result was only author description and ASR is on.
        prior_src = str(sub.get("source") or "")
        if prior_src not in {"description", "title", "summary", "content", "media_content", "media_summary", "media_title"}:
            return {"status": "SUCCESS", "skipped": True, "subtitle": sub}
        if not settings.av_asr_enabled:
            return {"status": "SUCCESS", "skipped": True, "subtitle": sub}

    platform = str(meta.get("platform") or _platform_from_url(item.url or "")).lower()
    is_douyin = platform in {"douyin", "dy"} or "douyin" in (item.url or "").lower()
    out_root = Path(settings.data_dir) / "av" / "subs" / str(item.id)
    out_root.mkdir(parents=True, exist_ok=True)

    text = ""
    source = "subtitle"
    note = None
    path_out: str | None = None
    last_reason = "no_text"
    remote_result: dict[str, Any] = {}

    # 1) Platform soft CC via yt-dlp
    if on_progress:
        on_progress(current=2, total=10, message=f"拉取平台字幕轨 {item.title[:40]}…", percent=15.0)
    remote_result = extract_subtitles_only(
        item.url,
        out_dir=out_root,
        settings=settings,
        on_progress=on_progress,
    )
    if remote_result.get("status") == "done" and (remote_result.get("subtitle_text") or "").strip():
        text = (remote_result.get("subtitle_text") or "").strip()
        source = "subtitle"
        path_out = remote_result.get("subtitle_path")
    else:
        last_reason = str(remote_result.get("reason") or "no_subtitle_tracks")

    # 2) Local soft-sub demux (Bilibili/YouTube embeds sometimes)
    local_media = find_local_av_media(str(item.id), settings=settings)
    if not text and local_media is not None:
        if on_progress:
            on_progress(current=3, total=10, message="检查本地文件字幕轨…", percent=30.0)
        probe = probe_media_streams(local_media, settings=settings)
        soft = extract_soft_subtitles(local_media, out_dir=out_root, settings=settings)
        if soft.get("status") == "done" and (soft.get("subtitle_text") or "").strip():
            text = (soft.get("subtitle_text") or "").strip()
            source = "soft_sub"
            path_out = soft.get("subtitle_path")
            note = "从本地容器抽出独立字幕轨"
        else:
            last_reason = str(soft.get("reason") or last_reason)
            if probe.get("ok") and not probe.get("has_soft_subs"):
                last_reason = "no_soft_subs"

    # 3) ASR on local audio (handles Douyin burned-in / spoken captions)
    asr_result: dict[str, Any] = {}
    if not text and local_media is not None and settings.av_asr_enabled:
        if on_progress:
            on_progress(current=5, total=10, message="平台无字幕轨，对本地音轨 ASR…", percent=50.0)
        asr_result = transcribe_local_media(
            local_media,
            work_dir=out_root,
            settings=settings,
            on_progress=on_progress,
        )
        if asr_result.get("status") == "done" and (asr_result.get("text") or "").strip():
            text = (asr_result.get("text") or "").strip()
            source = "asr"
            note = f"本地音轨语音识别（{asr_result.get('backend') or asr_result.get('reason')}）"
        else:
            last_reason = str(asr_result.get("reason") or last_reason)

    # 4) Optional author description — NOT on-screen captions (off by default)
    if not text and settings.av_fallback_author_desc:
        if on_progress:
            on_progress(current=8, total=10, message="回退作者简介（非字幕）…", percent=80.0)
        desc_info = fetch_entry_description(
            item.url,
            settings=settings,
            on_progress=on_progress,
        )
        desc = (desc_info.get("description") or "").strip() if desc_info.get("status") == "done" else ""
        if len(desc) >= 12:
            text = desc
            source = "description"
            note = "非字幕：平台作者简介/描述（AV_FALLBACK_AUTHOR_DESC=true）"
        else:
            candidates: list[tuple[str, str]] = []
            if (item.summary or "").strip():
                candidates.append(((item.summary or "").strip(), "summary"))
            mid = meta.get("from_media_id")
            if mid:
                try:
                    media = session.get(IntelItem, uuid.UUID(str(mid)))
                except (TypeError, ValueError):
                    media = None
                if media is not None:
                    for field, label in (
                        (media.content, "media_content"),
                        (media.summary, "media_summary"),
                    ):
                        body = (field or "").strip()
                        if len(body) >= 12:
                            candidates.append((body, label))
            if candidates:
                candidates.sort(key=lambda x: len(x[0]), reverse=True)
                text, source = candidates[0]
                note = "非字幕：抓取简介（AV_FALLBACK_AUTHOR_DESC=true）"

    meta = dict(meta)
    if text:
        item.content = text[:50000]
        meta["subtitle"] = {
            "status": "done",
            "source": source,
            "path": path_out,
            "text_preview": text[:500],
            "chars": len(text),
            "error": None,
            "note": note,
        }
        item.metadata_ = meta
        session.flush()
        if on_progress:
            on_progress(current=10, total=10, message=f"文稿就绪（来源：{source}）", percent=100.0)
        return {
            "status": "SUCCESS",
            "subtitle": meta["subtitle"],
            "fallback": source not in {"subtitle", "soft_sub", "asr"},
        }

    # Failure — explain burned-in vs missing ASR clearly.
    bits: list[str] = []
    if is_douyin or last_reason in {"no_subtitle_tracks", "no_soft_subs"}:
        bits.append(burned_in_caption_note())
    if local_media is None:
        bits.append("请先下载视频，再提取文稿（ASR 依赖本地音轨）。")
    elif not settings.av_asr_enabled:
        bits.append(
            "ASR 未启用：.env 设 AV_ASR_ENABLED=true，并配置云端 Whisper 或安装 faster-whisper。"
        )
    elif asr_result.get("status") in {"failed", "skipped"}:
        asr_err = (asr_result.get("error") or "").strip()
        bits.append(
            asr_err
            or (
                "ASR 未产生文稿。请在系统设置→配置填写火山 ASR 密钥，"
                "或设 AV_ASR_BACKEND=openai / 安装 faster-whisper。"
            )
        )
    elif remote_result.get("error"):
        bits.append(str(remote_result.get("error")))
    err = " ".join(bits) if bits else (remote_result.get("error") or "未能提取文稿")

    meta["subtitle"] = {
        "status": "failed",
        "source": None,
        "path": None,
        "text_preview": None,
        "error": err,
        "reason": last_reason,
    }
    item.metadata_ = meta
    session.flush()
    return {"status": "FAILED", "error": err, "subtitle": meta["subtitle"]}

