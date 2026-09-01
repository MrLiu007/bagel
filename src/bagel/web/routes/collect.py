"""Manual collect / digest triggers with progress polling."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from bagel.services.tasks import task_manager
from bagel.web.nav import NAV_ITEMS
from bagel.web.templating import templates

router = APIRouter(tags=["collect"])

ALLOWED_KINDS = {
    "collect_news",
    "collect_github",
    "collect_papers",
    "collect_stocks",
    "enrich_stocks",
    "collect_all",
    "summarize",
    "build_digest",
    "build_monthly_briefs",
}


@router.get("/collect", response_class=HTMLResponse)
async def collect_page(request: Request) -> HTMLResponse:
    latest = task_manager.latest()
    from bagel.settings import get_settings

    return templates.TemplateResponse(
        request,
        "collect.html",
        {
            "title": "手动采集",
            "active": "collect",
            "nav": NAV_ITEMS,
            "lookback_days": get_settings().collect_lookback_days,
            "latest": latest.to_dict() if latest else None,
            "recent": [t.to_dict() for t in task_manager.list_recent(8)],
        },
    )


@router.post("/api/tasks/start")
async def start_task(
    request: Request,
    kind: str = Form(...),
    cn_only: str | None = Form(None),
) -> JSONResponse:
    if kind not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail=f"不支持的任务: {kind}")
    options: dict = {"cn_only": cn_only in {"1", "true", "on", "yes"}}
    uid = request.session.get("user_id")
    if uid:
        options["owner_id"] = uid
    state = task_manager.start(kind, options=options)
    return JSONResponse(state.to_dict())


@router.get("/api/tasks/latest")
async def latest_task(kind: str | None = None) -> JSONResponse:
    state = task_manager.latest(kind)
    if state is None:
        return JSONResponse({"task": None})
    return JSONResponse({"task": state.to_dict()})


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> JSONResponse:
    state = task_manager.get(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return JSONResponse(state.to_dict())


@router.get("/api/tasks")
async def list_tasks() -> JSONResponse:
    return JSONResponse({"tasks": [t.to_dict() for t in task_manager.list_recent(20)]})
