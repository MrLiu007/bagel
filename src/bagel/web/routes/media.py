"""自媒体 API — 抓取任务与状态（列表页在 review 路由）。"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from bagel.integrations.mediacrawler import _normalize_keywords, status_dict
from bagel.services.tasks import task_manager
from bagel.settings import get_settings

router = APIRouter(tags=["media"])


@router.post("/api/media/crawl")
async def media_crawl_api(
    request: Request,
    platforms: list[str] = Form(default=[]),
    keywords: str = Form(""),
) -> JSONResponse:
    opts: dict = {}
    if platforms:
        opts["platforms"] = platforms
    cleaned = _normalize_keywords([keywords] if keywords.strip() else [])
    if cleaned:
        opts["keywords"] = cleaned
    if request.session.get("user_id"):
        opts["owner_id"] = request.session.get("user_id")
    state = task_manager.start("collect_media", options=opts)
    return JSONResponse(state.to_dict())


@router.get("/api/media/status")
async def media_status() -> JSONResponse:
    return JSONResponse(status_dict(get_settings()))
