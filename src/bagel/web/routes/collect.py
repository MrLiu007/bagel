"""Collect UI — manual triggers, scheduled history, and task detail."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from bagel.services.tasks import task_manager
from bagel.web.nav import NAV_ITEMS
from bagel.web.templating import templates

router = APIRouter(tags=["collect"])

ALLOWED_KINDS = {
    "collect_news",
    "collect_github",
    "collect_papers",
    "collect_education",
    "collect_models",
    "collect_stocks",
    "collect_all",
    "summarize",
    "compile_wiki",
}


def _session_owner(request: Request) -> str | None:
    uid = request.session.get("user_id")
    return str(uid) if uid else None


def _can_view_task(request: Request, task) -> bool:
    oid = _session_owner(request)
    if oid is None:
        return True
    if task.trigger == "scheduled" and not task.owner_id:
        return True
    if request.session.get("is_admin") and not task.owner_id:
        return True
    return str(task.owner_id or "") == oid


def _detail_context(request: Request, task_id: str) -> dict | None:
    state = task_manager.get(task_id)
    if state is None:
        return None
    if not _can_view_task(request, state):
        return None
    data = state.to_dict()
    result = data.get("result") or {}
    source_stats = result.get("source_stats") if isinstance(result, dict) else None
    if not isinstance(source_stats, list):
        source_stats = []
    return {
        "task": data,
        "result": result if isinstance(result, dict) else {},
        "source_stats": source_stats,
        "back_tab": "scheduled" if data.get("trigger") == "scheduled" else "manual",
    }


@router.get("/collect", response_class=HTMLResponse)
async def collect_page(
    request: Request,
    tab: str = Query("manual"),
) -> HTMLResponse:
    tab_key = tab if tab in {"manual", "scheduled"} else "manual"
    trigger = "manual" if tab_key == "manual" else "scheduled"
    from bagel.settings import get_settings

    owner = _session_owner(request)
    latest = (
        task_manager.latest(trigger=trigger, owner_id=owner) if tab_key == "manual" else None
    )
    return templates.TemplateResponse(
        request,
        "collect.html",
        {
            "title": "采集",
            "active": "collect",
            "nav": NAV_ITEMS,
            "tab": tab_key,
            "lookback_days": get_settings().collect_lookback_days,
            "latest": latest.to_dict() if latest else None,
            "recent": [
                t.to_dict()
                for t in task_manager.list_recent(20, trigger=trigger, owner_id=owner)
            ],
        },
    )


@router.get("/collect/tasks/{task_id}", response_class=HTMLResponse)
async def collect_task_detail(request: Request, task_id: str) -> HTMLResponse:
    ctx = _detail_context(request, task_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="任务不存在或无权查看")
    return templates.TemplateResponse(
        request,
        "collect_task_detail.html",
        {
            "title": "任务详情",
            "active": "collect",
            "nav": NAV_ITEMS,
            **ctx,
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
    options: dict = {
        "cn_only": cn_only in {"1", "true", "on", "yes"},
        "trigger": "manual",
    }
    uid = request.session.get("user_id")
    if uid:
        options["owner_id"] = uid
    state = task_manager.start(kind, options=options)
    return JSONResponse(state.to_dict())


@router.get("/api/tasks/latest")
async def latest_task(
    request: Request,
    kind: str | None = None,
    trigger: str | None = None,
) -> JSONResponse:
    state = task_manager.latest(kind, trigger=trigger, owner_id=_session_owner(request))
    if state is None:
        return JSONResponse({"task": None})
    return JSONResponse({"task": state.to_dict()})


@router.get("/api/tasks/{task_id}")
async def get_task(request: Request, task_id: str) -> JSONResponse:
    state = task_manager.get(task_id)
    if state is None or not _can_view_task(request, state):
        raise HTTPException(status_code=404, detail="任务不存在")
    return JSONResponse(state.to_dict())


@router.get("/api/tasks")
async def list_tasks(request: Request, trigger: str | None = None) -> JSONResponse:
    if trigger and trigger not in {"manual", "scheduled"}:
        raise HTTPException(status_code=400, detail="trigger 仅支持 manual / scheduled")
    return JSONResponse(
        {
            "tasks": [
                t.to_dict()
                for t in task_manager.list_recent(
                    20, trigger=trigger, owner_id=_session_owner(request)
                )
            ]
        }
    )
