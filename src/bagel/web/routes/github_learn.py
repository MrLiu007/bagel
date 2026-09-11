"""GitHub 「学习」— Qoder-style wiki reading + Archify diagram."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemType
from bagel.domain.models import IntelItem
from bagel.integrations.archify import status_dict as archify_status
from bagel.services.github_learn import learn_dir, load_learn_bundle
from bagel.services.tasks import task_manager
from bagel.settings import get_settings
from bagel.storage.database import get_db
from bagel.web.nav import NAV_ITEMS
from bagel.web.routes.briefs import markdown_to_article_html
from bagel.web.templating import templates

router = APIRouter(tags=["github-learn"])


@router.post("/api/github/learn/{item_id}")
async def github_learn_start(item_id: UUID, request: Request) -> JSONResponse:
    force = False
    try:
        body = await request.json()
        force = bool(body.get("force"))
    except Exception:  # noqa: BLE001
        force = False
    state = task_manager.start(
        "github_learn",
        options={"item_id": str(item_id), "force": force},
    )
    return JSONResponse(state.to_dict())


@router.post("/api/github/learn/{item_id}/pages/{page_file}")
async def github_learn_page_start(
    item_id: UUID, page_file: str, request: Request
) -> JSONResponse:
    force = False
    try:
        body = await request.json()
        force = bool(body.get("force"))
    except Exception:  # noqa: BLE001
        force = False
    state = task_manager.start(
        "github_learn_page",
        options={
            "item_id": str(item_id),
            "page_file": page_file,
            "force": force,
        },
    )
    return JSONResponse(state.to_dict())


@router.get("/api/github/learn-status")
async def github_learn_status() -> JSONResponse:
    s = get_settings()
    return JSONResponse(
        {
            "enabled": s.enable_github_learn,
            "archify": archify_status(s),
        }
    )


@router.get("/github/learn/{item_id}", response_class=HTMLResponse)
async def github_learn_page(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
    page: str | None = None,
) -> HTMLResponse:
    item = db.get(IntelItem, item_id)
    if not item or item.item_type not in {ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE}:
        raise HTTPException(status_code=404, detail="条目不存在")
    settings = get_settings()
    bundle = load_learn_bundle(settings, item_id)
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    learn = meta.get("learn") if isinstance(meta.get("learn"), dict) else {}
    pages = (bundle or {}).get("pages") or []
    active = None
    article_html = ""
    if pages:
        if page:
            active = next(
                (p for p in pages if p.get("file") == page or p.get("title") == page),
                pages[0],
            )
        else:
            active = pages[0]
        if active and active.get("status") != "pending" and active.get("markdown"):
            article_html = markdown_to_article_html(str(active.get("markdown") or ""))
    ready_n = sum(1 for p in pages if p.get("status") == "ready")
    return templates.TemplateResponse(
        request,
        "github_learn.html",
        {
            "title": f"学习 · {item.title}",
            "nav": NAV_ITEMS,
            "active": "github",
            "item": item,
            "item_id": str(item.id),
            "learn": learn,
            "bundle": bundle,
            "pages": pages,
            "active_page": active,
            "article_html": article_html,
            "has_diagram": bool(bundle and bundle.get("diagram_exists")),
            "ready": bool(bundle),
            "page_pending": bool(active and active.get("status") == "pending"),
            "pages_ready": ready_n,
            "pages_total": len(pages),
        },
    )


@router.get("/api/github/learn/{item_id}/diagram")
async def github_learn_diagram(item_id: UUID) -> FileResponse:
    settings = get_settings()
    html = learn_dir(settings, item_id) / "architecture.html"
    if not html.is_file():
        raise HTTPException(status_code=404, detail="架构图尚未生成")
    return FileResponse(html, media_type="text/html; charset=utf-8")
