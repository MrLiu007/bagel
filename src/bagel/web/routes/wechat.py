"""微信：消息（Gewe）+ 公众号文章（URL 拉取 / 详情 / 本地媒体）。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType
from bagel.domain.models import IntelItem
from bagel.integrations.gewe import GeweClient, GeweError, status as gewe_status
from bagel.integrations.wechat_mp_media import item_media_dir
from bagel.jobs.wechat import ingest_wechat_payload
from bagel.jobs.wechat_mp import ingest_wechat_article_url, relocalize_item_media
from bagel.services import review as review_svc
from bagel.services import settings_svc
from bagel.settings import get_settings
from bagel.storage.database import get_db
from bagel.storage.repositories import ItemRepository
from bagel.web.nav import NAV_ITEMS
from bagel.web.routes.review import _log_list_search, _owner_id, _page
from bagel.web.templating import present_item, templates

router = APIRouter(tags=["wechat"])


def _wechat_tabs(active: str) -> list[dict[str, str]]:
    return [
        {"key": "messages", "label": "微信消息", "url": "/wechat?tab=messages", "on": active == "messages"},
        {"key": "accounts", "label": "微信公众号", "url": "/wechat?tab=accounts", "on": active == "accounts"},
    ]


def _mp_source_rows(sources: list) -> tuple[list[dict], bool, str]:
    from bagel.integrations.wechat_mp_discover import parse_source_url
    from bagel.services.wewe_runtime import effective_wewe_base_url, probe_feeds

    base = effective_wewe_base_url()
    wewe_ready = bool(base) and probe_feeds(base, timeout=1.5)
    rows: list[dict] = []
    for s in sources:
        ref = parse_source_url(s.url or "")
        rows.append(
            {
                "id": s.id,
                "name": s.name,
                "wxid": ref.wxid,
                "biz": ref.biz,
                "feed_url": ref.feed_url,
                "enabled": s.enabled,
                "last_error_code": s.last_error_code,
                "last_success_at": s.last_success_at,
                "url": s.url,
            }
        )
    return rows, wewe_ready, base or ""


@router.get("/wechat", response_class=HTMLResponse)
async def wechat_page(
    request: Request,
    db: Session = Depends(get_db),
    tab: str = Query("messages"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    q: str | None = Query(None, description="Title keyword"),
    account: str | None = Query(None, description="公众号名称过滤"),
) -> HTMLResponse:
    active_tab = tab if tab in {"messages", "accounts"} else "messages"
    owner = _owner_id(request)
    pull_message = request.query_params.get("msg")
    pull_error = request.query_params.get("err")

    if active_tab == "accounts":
        result = review_svc.list_candidates(
            db,
            item_type=ItemType.WECHAT_ARTICLE,
            category=category,
            owner_id=owner,
            q=q,
            author=account or None,
            page=page,
            page_size=page_size,
        )
        _log_list_search(
            db,
            q=q,
            item_type=ItemType.WECHAT_ARTICLE,
            hit_count=result.total,
            owner_id=owner,
        )
        accounts = list(
            ItemRepository(db).list_authors(
                ItemStatus.CANDIDATE,
                item_type=ItemType.WECHAT_ARTICLE,
                owner_id=owner,
            )
        )
        settings = get_settings()
        proxy_ready = bool(settings.proxy_url)
        mp_sources, wewe_ready, wewe_base = _mp_source_rows(
            settings_svc.list_wechat_mp_sources(db)
        )
        return _page(
            request,
            title="微信",
            result=result,
            active="wechat",
            category=category,
            q=q,
            author=account or None,
            template="wechat.html",
            extra={
                "wechat_tab": active_tab,
                "wechat_tabs": _wechat_tabs(active_tab),
                "accounts": accounts,
                "account_filter": account or "",
                "empty_hint": "暂无文章。订阅时填写 WeWe-RSS 源或该号样例文章链接，再「立即采集」。",
                "pull_message": pull_message,
                "pull_error": pull_error,
                "proxy_ready": proxy_ready,
                "network_mode": settings.network_mode.value,
                "list_extra_params": {"tab": "accounts"},
                "list_compact": True,
                "mp_sources": mp_sources,
                "wewe_ready": wewe_ready,
                "wewe_base": wewe_base,
                "sogou_enabled": bool(settings.wechat_mp_enable_sogou),
            },
        )

    st = gewe_status()
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
            "wechat_tab": active_tab,
            "wechat_tabs": _wechat_tabs(active_tab),
            "status": st,
            "online": online,
            "online_error": online_error,
            "empty_hint": "暂无微信消息。配置回调后，含关键词的消息会出现在此。",
            "callback_url": get_settings().gewe_callback_url,
            "list_extra_params": {"tab": "messages"},
        },
    )


@router.get("/wechat/articles/{item_id}", response_class=HTMLResponse)
async def wechat_article_detail(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    item = db.get(IntelItem, item_id)
    if item is None or item.item_type != ItemType.WECHAT_ARTICLE:
        raise HTTPException(status_code=404, detail="条目不存在")
    presented = present_item(item, preview=False)
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    mp = meta.get("wechat_mp") if isinstance(meta.get("wechat_mp"), dict) else {}
    return templates.TemplateResponse(
        request,
        "wechat_article.html",
        {
            "title": item.title or "公众号文章",
            "active": "wechat",
            "nav": NAV_ITEMS,
            "item": presented,
            "body_html": presented.get("summary_html") or "",
            "asset_count": int(mp.get("asset_count") or 0),
            "media_localized": bool(mp.get("media_localized")),
            "media_skipped": list(mp.get("media_skipped") or [])[:8],
            "account": item.author or mp.get("account") or "",
            "source_url": item.url or "",
        },
    )


@router.post("/wechat/accounts/subscribe")
async def wechat_mp_subscribe(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(""),
    wxid: str = Form(""),
    feed_url: str = Form(""),
    sample_url: str = Form(""),
) -> RedirectResponse:
    owner = _owner_id(request)
    cleaned_name = (name or "").strip()
    cleaned_wxid = (wxid or "").strip()
    cleaned_feed = (feed_url or "").strip()
    sample = (sample_url or "").strip()
    biz = ""
    seed_msg = ""

    if sample:
        from bagel.integrations.wechat_mp import WechatMpError, fetch_mp_article
        from bagel.integrations.wewe_rss import WeweRssClient

        try:
            article = fetch_mp_article(sample)
        except WechatMpError as exc:
            err = quote(exc.message[:200])
            return RedirectResponse(url=f"/wechat?tab=accounts&err={err}", status_code=303)
        if not cleaned_name and article.account:
            cleaned_name = article.account
        biz = getattr(article, "biz", "") or ""
        # Auto-bind WeWe feed when possible
        if not cleaned_feed and cleaned_name:
            client = WeweRssClient()
            matched = client.match_feed(name=cleaned_name) if client.enabled else None
            if matched:
                cleaned_feed = client.feed_json_url(matched.id, limit=12)
        # Seed ingest sample article
        seed = ingest_wechat_article_url(db, sample, owner_id=owner, account_hint=cleaned_name)
        if seed.get("ok"):
            seed_msg = f"已入库样例「{(seed.get('title') or '')[:40]}」"

    try:
        src = settings_svc.add_wechat_mp_source(
            db,
            name=cleaned_name,
            wxid=cleaned_wxid,
            biz=biz,
            feed_url=cleaned_feed,
        )
    except settings_svc.SettingsError as exc:
        err = quote(exc.message[:200])
        return RedirectResponse(url=f"/wechat?tab=accounts&err={err}", status_code=303)

    bits = [f"已订阅「{src.name}」"]
    if cleaned_feed:
        bits.append("已绑定 RSS 源")
    if seed_msg:
        bits.append(seed_msg)
    msg = quote(" · ".join(bits))
    return RedirectResponse(url=f"/wechat?tab=accounts&msg={msg}", status_code=303)


@router.post("/wechat/accounts/sources/{source_id}/toggle")
async def wechat_mp_toggle(
    source_id: UUID,
    db: Session = Depends(get_db),
    enabled: str = Form("1"),
) -> RedirectResponse:
    try:
        settings_svc.toggle_wechat_mp_source(
            db, source_id, enabled=enabled in {"1", "true", "on"}
        )
    except settings_svc.SettingsError as exc:
        err = quote(exc.message[:200])
        return RedirectResponse(url=f"/wechat?tab=accounts&err={err}", status_code=303)
    return RedirectResponse(url="/wechat?tab=accounts", status_code=303)


@router.post("/wechat/accounts/sources/{source_id}/delete")
async def wechat_mp_delete(
    source_id: UUID,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        settings_svc.delete_wechat_mp_source(db, source_id)
    except settings_svc.SettingsError as exc:
        err = quote(exc.message[:200])
        return RedirectResponse(url=f"/wechat?tab=accounts&err={err}", status_code=303)
    return RedirectResponse(url="/wechat?tab=accounts", status_code=303)


@router.post("/wechat/accounts/pull")
async def wechat_account_pull_form(
    request: Request,
    db: Session = Depends(get_db),
    url: str = Form(...),
) -> RedirectResponse:
    """No-JS fallback: form POST then redirect."""
    owner = _owner_id(request)
    result = ingest_wechat_article_url(db, url, owner_id=owner)
    if not result.get("ok"):
        err = quote(str(result.get("error") or "拉取失败")[:200])
        return RedirectResponse(url=f"/wechat?tab=accounts&err={err}", status_code=303)
    detail = result.get("detail_url") or "/wechat?tab=accounts"
    return RedirectResponse(url=str(detail), status_code=303)


@router.post("/api/wechat/accounts/pull")
async def wechat_account_pull_api(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """JSON pull with progress-friendly response for the accounts UI."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        form = await request.form()
        payload = {"url": str(form.get("url") or "")}
    url = str((payload or {}).get("url") or "").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "请粘贴公众号文章链接"}, status_code=400)
    owner = _owner_id(request)
    result = ingest_wechat_article_url(db, url, owner_id=owner)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@router.post("/api/wechat/articles/{item_id}/relocalize")
async def wechat_article_relocalize(
    item_id: UUID,
    db: Session = Depends(get_db),
) -> JSONResponse:
    result = relocalize_item_media(db, item_id)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


@router.get("/api/wechat/articles/{item_id}/media/{filename}")
async def wechat_article_media(
    item_id: UUID,
    filename: str,
) -> FileResponse:
    name = Path(filename).name
    if not name or name != filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    root = item_media_dir(item_id).resolve()
    path = (root / name).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="非法路径") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="媒体不存在")
    suffix = path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
    }
    return FileResponse(
        path,
        media_type=media_types.get(suffix, "application/octet-stream"),
        filename=name,
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
