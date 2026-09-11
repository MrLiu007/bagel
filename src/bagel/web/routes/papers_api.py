"""Papers API — PDF download + MinerU/Kimi document parse."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from bagel.services import user_config as user_cfg
from bagel.services.paper_parse import status_dict
from bagel.services.tasks import task_manager

router = APIRouter(tags=["papers"])


def _session_owner(request: Request) -> str | None:
    raw = request.session.get("user_id")
    return str(raw) if raw else None


@router.post("/api/papers/resolve-pdf/{item_id}")
async def papers_resolve_pdf_api(request: Request, item_id: UUID) -> JSONResponse:
    opts: dict = {"item_id": str(item_id)}
    oid = _session_owner(request)
    if oid:
        opts["owner_id"] = oid
    state = task_manager.start("resolve_paper_pdf", options=opts)
    return JSONResponse(state.to_dict())


@router.post("/api/papers/parse/{item_id}")
async def papers_parse_api(request: Request, item_id: UUID) -> JSONResponse:
    opts: dict = {"item_id": str(item_id)}
    oid = _session_owner(request)
    if oid:
        opts["owner_id"] = oid
    state = task_manager.start("parse_paper", options=opts)
    return JSONResponse(state.to_dict())


@router.get("/api/papers/parse-status")
async def papers_parse_status(request: Request) -> JSONResponse:
    settings = user_cfg.settings_for_user(_session_owner(request))
    return JSONResponse(status_dict(settings))