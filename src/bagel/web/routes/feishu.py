"""Feishu inbound events + command API (public, no login)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from bagel.storage.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["feishu"])


@router.post("/api/feishu/events")
async def feishu_events(request: Request) -> JSONResponse:
    """Feishu event subscription callback (URL verification + im.message)."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "expected_object"}, status_code=400)
    try:
        from bagel.integrations import feishu_bot

        body = feishu_bot.handle_event_payload(payload)
        return JSONResponse(body)
    except Exception as exc:  # noqa: BLE001
        logger.exception("feishu.events_error")
        return JSONResponse({"ok": False, "error": str(exc)[:200]}, status_code=400)


@router.post("/api/feishu/command")
async def feishu_command(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    """Direct command API. Body: {\"text\": \"...\", \"push\": true?}."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "expected_object"}, status_code=400)
    text = str(payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "text required"}, status_code=400)

    from bagel.services.feishu_command import handle_command

    result = handle_command(db, text)
    push = str(payload.get("push") or "").lower() in {"1", "true", "yes", "on"}
    push_result = None
    if push:
        from bagel.integrations import feishu_cli

        last_ok = True
        err = None
        for chunk in result.chunks[:6]:
            r = feishu_cli.send_text(chunk)
            if not r.ok:
                last_ok = False
                err = r.error or r.stderr
                break
        push_result = {"ok": last_ok, "error": err}

    return JSONResponse(
        {
            "ok": result.ok,
            "matched": result.matched,
            "crawled": result.crawled,
            "crawl_created": result.crawl_created,
            "chunks": result.chunks,
            "text": result.text,
            "push": push_result,
            "parsed": {
                "kind": result.parsed.kind if result.parsed else None,
                "keyword": result.parsed.keyword if result.parsed else None,
                "type_label": result.parsed.type_label if result.parsed else None,
                "start": result.parsed.start.isoformat()
                if result.parsed and result.parsed.start
                else None,
                "end": result.parsed.end.isoformat() if result.parsed and result.parsed.end else None,
            },
        }
    )


@router.get("/api/feishu/status")
async def feishu_status() -> JSONResponse:
    from bagel.integrations import feishu_bot, feishu_cli
    from bagel.services.runtime_config import load_runtime_config

    cfg = load_runtime_config()
    st = feishu_cli.status()
    return JSONResponse(
        {
            "outbound": st.as_dict(),
            "bot_app_configured": feishu_bot.bot_configured(),
            "events_url": "/api/feishu/events",
            "command_url": "/api/feishu/command",
            "feishu_push_after_collect": cfg.feishu_push_after_collect,
        }
    )
