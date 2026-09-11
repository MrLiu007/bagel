"""音视频 API — 元数据采集、按需下载、字幕提取与本地文件访问。"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemType
from bagel.domain.models import IntelItem
from bagel.integrations.ytdlp import status_dict
from bagel.services.tasks import task_manager
from bagel.settings import get_settings
from bagel.storage.database import get_db
from bagel.web.nav import NAV_ITEMS
from bagel.web.templating import present_item, templates
from bagel.services.av_bridge import enrich_media_transcript, import_media_post_to_av

router = APIRouter(tags=["av"])


@router.post("/api/av/collect")
async def av_collect_api(request: Request) -> JSONResponse:
    """Metadata-only scan of configured sources (no media files)."""
    opts: dict = {}
    if request.session.get("user_id"):
        opts["owner_id"] = request.session.get("user_id")
    state = task_manager.start("collect_av", options=opts)
    return JSONResponse(state.to_dict())

@router.post("/api/av/download/{item_id}")
async def av_download_api(request: Request, item_id: UUID) -> JSONResponse:
    opts: dict = {"item_id": str(item_id)}
    if request.session.get("user_id"):
        opts["owner_id"] = request.session.get("user_id")
    state = task_manager.start("download_av", options=opts)
    return JSONResponse(state.to_dict())


@router.post("/api/av/subtitles/{item_id}")
async def av_subtitles_api(request: Request, item_id: UUID) -> JSONResponse:
    opts: dict = {"item_id": str(item_id)}
    if request.session.get("user_id"):
        opts["owner_id"] = request.session.get("user_id")
    state = task_manager.start("extract_av_subtitles", options=opts)
    return JSONResponse(state.to_dict())


@router.get("/api/av/status")
async def av_status() -> JSONResponse:
    return JSONResponse(status_dict(get_settings()))


@router.get("/av/items/{item_id}", response_class=HTMLResponse)
async def av_item_detail(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    item = db.get(IntelItem, item_id)
    if not item or item.item_type != ItemType.AV:
        raise HTTPException(status_code=404, detail="条目不存在")
    from bagel.jobs.av import heal_av_local_download

    if heal_av_local_download(item):
        db.commit()
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    dl = meta.get("download") if isinstance(meta.get("download"), dict) else {}
    sub = meta.get("subtitle") if isinstance(meta.get("subtitle"), dict) else {}
    subtitle_body = (item.content or sub.get("text_preview") or "").strip()
    vm = present_item(item)
    duration = meta.get("duration_sec")
    duration_label = ""
    if duration:
        mins, secs = divmod(int(duration), 60)
        duration_label = f"{mins}:{secs:02d}" if mins else f"{secs}s"
    return templates.TemplateResponse(
        request,
        "av_item.html",
        {
            "title": item.title[:120],
            "active": "av",
            "nav": NAV_ITEMS,
            "item": vm,
            "meta": meta,
            "download": dl,
            "subtitle": sub,
            "subtitle_body": subtitle_body,
            "duration_label": duration_label,
            "thumbnail": meta.get("thumbnail_url"),
            "platform": meta.get("platform") or "",
            "return_url": request.headers.get("referer") or "/av",
        },
    )


@router.post("/api/av/import-from-media/{item_id}")
async def av_import_from_media_api(
    item_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Promote a MediaCrawler video post into the AV learning queue."""
    owner_id = None
    raw = request.session.get("user_id")
    if raw:
        try:
            owner_id = UUID(str(raw))
        except (TypeError, ValueError):
            owner_id = None
    try:
        result = import_media_post_to_av(db, item_id, owner_id=owner_id)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(
        {
            "av_item_id": str(result.av_item.id),
            "created": result.created,
            "detail_url": result.detail_url,
        }
    )


@router.post("/api/av/enrich-from-media/{item_id}")
async def av_enrich_from_media_api(item_id: UUID, request: Request) -> JSONResponse:
    """Import media video + extract subtitles via yt-dlp (async task)."""
    opts: dict = {"item_id": str(item_id)}
    if request.session.get("user_id"):
        opts["owner_id"] = request.session.get("user_id")
    state = task_manager.start("enrich_media_transcript", options=opts)
    return JSONResponse(state.to_dict())


@router.get("/api/av/files/{item_id}")
async def av_file_api(
    item_id: UUID,
    db: Session = Depends(get_db),
) -> FileResponse:
    item = db.get(IntelItem, item_id)
    if not item or item.item_type != ItemType.AV:
        raise HTTPException(status_code=404, detail="条目不存在")
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    dl = meta.get("download") if isinstance(meta.get("download"), dict) else {}
    rel = (dl.get("local_path") or "").strip()
    if dl.get("status") != "done" or not rel:
        raise HTTPException(status_code=404, detail="尚未下载或文件不可用")
    settings = get_settings()
    path = Path(rel)
    if not path.is_absolute():
        path = (Path.cwd() / rel).resolve()
    root = (Path.cwd() / settings.data_dir / "av" / "files").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="非法路径") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = "audio/mp4" if path.suffix.lower() in {".m4a", ".mp4"} else "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)
