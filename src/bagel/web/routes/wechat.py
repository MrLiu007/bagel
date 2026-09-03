"""微信（Gewe）页面与 Webhook。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemType
from bagel.integrations.gewe import GeweClient, GeweError, status as gewe_status
from bagel.jobs.wechat import ingest_wechat_payload
from bagel.services import review as review_svc
from bagel.settings import get_settings
from bagel.storage.database import get_db
from bagel.web.routes.review import _log_list_search, _owner_id, _page

router = APIRouter(tags=["wechat"])


@router.get("/wechat", response_class=HTMLResponse)
async def wechat_page(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    q: str | None = Query(None, description="Title keyword"),
) -> HTMLResponse:
    st = gewe_status()
    owner = _owner_id(request)
    result = review_svc.list_candidates(
        db,
        item_type=ItemType.WECHAT_MSG,
        category=category,
        owner_id=owner,
        q=q,
        page=page,
        page_size=page_size,
    )
    _log_list_search(
        db, q=q, item_type=ItemType.WECHAT_MSG, hit_count=result.total, owner_id=owner
    )

    online = None
    online_error = None
    if st.enabled and st.configured:
        try:
            online = GeweClient().check_online()
        except (GeweError, Exception) as exc:  # noqa: BLE001
            online_error = str(exc)[:200]

    return _page(
        request,
        title="微信",
        result=result,
        active="wechat",
        category=category,
        q=q,
        template="wechat.html",
        extra={
            "status": st,
            "online": online,
            "online_error": online_error,
            "empty_hint": "暂无微信条目。配置回调后，含关键词的消息会出现在此。",
            "callback_url": get_settings().gewe_callback_url,
            "docs_hint": "配置说明见仓库 docs/user-config-media-wechat.md",
        },
    )


@router.post("/api/wechat/webhook")
async def wechat_webhook(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "expected_object"}, status_code=400)
    result = ingest_wechat_payload(db, payload)
    return JSONResponse({"ok": True, **result})


@router.get("/api/wechat/status")
async def wechat_status_api() -> JSONResponse:
    st = gewe_status()
    return JSONResponse(
        {
            "enabled": st.enabled,
            "configured": st.configured,
            "has_token": st.has_token,
            "has_app_id": st.has_app_id,
            "callback_url": st.callback_url,
            "keywords": st.keywords,
        }
    )
