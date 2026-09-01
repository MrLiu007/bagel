"""Web review routes — news / github / favorites with DB pagination."""

from __future__ import annotations

from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemType
from bagel.services import review as review_svc
from bagel.storage.database import get_db
from bagel.web.nav import NAV_ITEMS
from bagel.web.templating import present_item, templates

router = APIRouter(tags=["review"])


def _owner_id(request: Request):
    raw = request.session.get("user_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _page_url(
    path: str,
    *,
    page: int,
    page_size: int,
    category: str | None = None,
    kind: str | None = None,
    platform: str | None = None,
) -> str:
    params: dict[str, str | int] = {"page": page, "page_size": page_size}
    if category:
        params["category"] = category
    if kind and kind != "all":
        params["kind"] = kind
    if platform:
        params["platform"] = platform
    return f"{path}?{urlencode(params)}"


def _safe_redirect(next_url: str | None, *, fallback: str = "/news") -> str:
    """Reject open redirects and strip internal fragment= query used by partial refresh."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    raw = (next_url or "").strip() or fallback
    if not raw.startswith("/") or raw.startswith("//"):
        return fallback
    parts = urlsplit(raw)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k != "fragment"
    ]
    return urlunsplit(("", "", parts.path or "/", urlencode(query), ""))


def _list_nav(
    path: str,
    *,
    result: review_svc.PageResult,
    category: str | None = None,
    kind: str | None = None,
    platform: str | None = None,
) -> dict:
    """Shared pagination / return / category URLs that preserve list filters."""
    total_pages = result.total_pages
    pages = []
    for p in range(1, total_pages + 1):
        if total_pages > 12 and abs(p - result.page) > 3 and p not in (1, total_pages):
            continue
        pages.append(
            {
                "num": p,
                "url": _page_url(
                    path,
                    page=p,
                    category=category,
                    page_size=result.page_size,
                    kind=kind,
                    platform=platform,
                ),
                "active": p == result.page,
            }
        )
    cat_all_url = _page_url(
        path,
        page=1,
        page_size=result.page_size,
        kind=kind,
        platform=platform,
    )
    category_urls = {
        c: _page_url(
            path,
            page=1,
            page_size=result.page_size,
            category=c,
            kind=kind,
            platform=platform,
        )
        for c in result.categories
    }
    return {
        "pages": pages,
        "total_pages": total_pages,
        "prev_url": (
            _page_url(
                path,
                page=result.page - 1,
                category=category,
                page_size=result.page_size,
                kind=kind,
                platform=platform,
            )
            if result.page > 1
            else None
        ),
        "next_url": (
            _page_url(
                path,
                page=result.page + 1,
                category=category,
                page_size=result.page_size,
                kind=kind,
                platform=platform,
            )
            if result.page < total_pages
            else None
        ),
        "base_path": path,
        "cat_all_url": cat_all_url,
        "category_urls": category_urls,
        "return_url": _page_url(
            path,
            page=result.page,
            category=category,
            page_size=result.page_size,
            kind=kind,
            platform=platform,
        ),
        "platform": platform or "",
        "kind": kind or "",
    }


def _page(
    request: Request,
    *,
    title: str,
    result: review_svc.PageResult,
    active: str,
    category: str | None = None,
    kind: str | None = None,
    platform: str | None = None,
    message: str | None = None,
    template: str = "items.html",
    extra: dict | None = None,
) -> HTMLResponse:
    path = request.url.path
    nav = _list_nav(path, result=result, category=category, kind=kind, platform=platform)
    ctx: dict = {
        "title": title,
        "items": [present_item(i) for i in result.items],
        "active": active,
        "nav": NAV_ITEMS,
        "message": message,
        "category": category or "",
        "categories": result.categories,
        "page": result.page,
        "page_size": result.page_size,
        "total": result.total,
        **nav,
    }
    if extra:
        ctx.update(extra)
    return templates.TemplateResponse(
        request,
        template,
        ctx,
    )


@router.get("/candidates", response_class=HTMLResponse)
async def candidates() -> RedirectResponse:
    return RedirectResponse(url="/news", status_code=303)


@router.get("/news", response_class=HTMLResponse)
async def news(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
) -> HTMLResponse:
    result = review_svc.list_candidates(
        db,
        item_type=ItemType.NEWS,
        category=category,
        owner_id=_owner_id(request),
        page=page,
        page_size=page_size,
    )
    return _page(request, title="AI新闻", result=result, active="news", category=category)


@router.get("/github", response_class=HTMLResponse)
async def github(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
) -> HTMLResponse:
    result = review_svc.list_candidates(
        db,
        item_type=ItemType.GITHUB_REPO,
        category=category,
        owner_id=_owner_id(request),
        page=page,
        page_size=page_size,
    )
    return _page(request, title="GitHub项目", result=result, active="github", category=category)


@router.get("/papers", response_class=HTMLResponse)
async def papers(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
) -> HTMLResponse:
    result = review_svc.list_candidates(
        db,
        item_type=ItemType.PAPER,
        category=category,
        owner_id=_owner_id(request),
        page=page,
        page_size=page_size,
    )
    return _page(request, title="论文", result=result, active="papers", category=category)


@router.get("/stocks", response_class=HTMLResponse)
async def stocks(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
) -> HTMLResponse:
    result = review_svc.list_candidates(
        db,
        item_type=ItemType.STOCK_NEWS,
        category=category,
        owner_id=_owner_id(request),
        page=page,
        page_size=page_size,
    )
    return _page(
        request,
        title="股票资讯",
        result=result,
        active="stocks",
        category=category,
        extra={
            "page_intro": (
                "国内外股市/宏观相关资讯（与 AI 新闻源隔离）。"
                "数据源可在 <a href=\"/settings?tab=stocks\">系统设置 → 股票数据源</a> 配置；"
                "采集请用手动采集中的「采集股票」。"
            ),
            "empty_hint": (
                "暂无股票资讯。请先在 "
                "<a href=\"/settings?tab=stocks\">系统设置 → 股票数据源</a> 确认源已启用，"
                "再前往 <a href=\"/collect\">手动采集</a> 点击「采集股票」。"
            ),
        },
    )


@router.get("/stocks/lab", response_class=HTMLResponse)
async def stocks_lab(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "stocks_lab.html",
        {
            "title": "量化研读台",
            "active": "stocks",
            "nav": NAV_ITEMS,
        },
    )


@router.get("/stocks/timeline", response_class=HTMLResponse)
async def stocks_timeline(
    request: Request,
    db: Session = Depends(get_db),
    days: int = Query(14, ge=3, le=60),
) -> HTMLResponse:
    from bagel.services import stock_events
    from bagel.settings import get_settings

    items = stock_events.list_stock_items(
        db,
        owner_id=_owner_id(request),
        days=days,
        limit=400,
    )
    db.commit()
    timeline = stock_events.build_timeline(items)
    symbols = stock_events.build_symbol_index(items)[:24]
    return templates.TemplateResponse(
        request,
        "stocks_timeline.html",
        {
            "title": "股票事件时间线",
            "active": "stocks",
            "nav": NAV_ITEMS,
            "days": days,
            "timeline": timeline,
            "symbols": symbols,
            "lookback": get_settings().stock_market_lookback_days,
            "present_item": present_item,
        },
    )


@router.get("/stocks/symbol/{symbol}", response_class=HTMLResponse)
async def stocks_symbol(
    request: Request,
    symbol: str,
    db: Session = Depends(get_db),
    days: int = Query(14, ge=3, le=60),
) -> HTMLResponse:
    from bagel.integrations import market_data
    from bagel.services import stock_events
    from bagel.settings import get_settings

    settings = get_settings()
    items = stock_events.list_stock_items(
        db,
        owner_id=_owner_id(request),
        days=days,
        limit=400,
    )
    db.commit()
    bundle = stock_events.get_symbol_bundle(items, symbol)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"近 {days} 天暂无与 {symbol} 关联的资讯")

    ohlc = None
    if settings.enable_stock_market_data:
        series = market_data.fetch_ohlc(bundle.symbol, settings=settings)
        ohlc = series.as_dict()

    events = []
    for item in bundle.items:
        pub = item.published_at
        if pub is None:
            continue
        events.append(
            {
                "t": int(pub.timestamp()),
                "title": item.title,
                "sentiment": stock_events.stock_meta(item).get("sentiment") or "neutral",
                "url": item.url,
            }
        )

    return templates.TemplateResponse(
        request,
        "stocks_symbol.html",
        {
            "title": f"{bundle.symbol} · 标的研读",
            "active": "stocks",
            "nav": NAV_ITEMS,
            "bundle": bundle,
            "items": [present_item(i) for i in bundle.items],
            "ohlc": ohlc,
            "events": events,
            "market_enabled": settings.enable_stock_market_data,
            "research_enabled": settings.enable_stock_research_draft,
            "days": days,
        },
    )


@router.post("/stocks/symbol/{symbol}/research", response_class=HTMLResponse)
async def stocks_symbol_research(
    request: Request,
    symbol: str,
    db: Session = Depends(get_db),
    days: int = Query(14, ge=3, le=60),
) -> HTMLResponse:
    from bagel.services import stock_research
    from bagel.web.routes.briefs import markdown_to_article_html

    draft = stock_research.build_research_draft(
        db,
        symbol=symbol,
        owner_id=_owner_id(request),
        days=days,
    )
    return templates.TemplateResponse(
        request,
        "stocks_research.html",
        {
            "title": f"{symbol.upper()} · 行研草稿",
            "active": "stocks",
            "nav": NAV_ITEMS,
            "draft": draft,
            "article_html": markdown_to_article_html(draft.markdown) if draft.markdown else "",
            "symbol": symbol.upper(),
        },
    )


@router.get("/api/stocks/ohlc/{symbol}")
async def stocks_ohlc_api(symbol: str) -> JSONResponse:
    from bagel.integrations import market_data
    from bagel.settings import get_settings

    series = market_data.fetch_ohlc(symbol, settings=get_settings())
    return JSONResponse(series.as_dict())


@router.get("/science", response_class=HTMLResponse)
async def science_redirect() -> RedirectResponse:
    return RedirectResponse(url="/papers", status_code=301)


@router.get("/media", response_class=HTMLResponse)
async def media(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    platform: str | None = Query(None),
    fragment: str | None = Query(None),
) -> HTMLResponse:
    from bagel.integrations.mediacrawler import MEDIA_PLATFORMS, PLATFORM_LABELS, status_dict
    from bagel.services.tasks import task_manager
    from bagel.settings import get_settings

    settings = get_settings()
    platform_key = (platform or "").strip().lower() or None
    if platform_key and platform_key not in PLATFORM_LABELS:
        platform_key = None
    # One-shot heal for older Weibo rows with title == content.
    from bagel.jobs.media import repair_media_duplicate_titles

    if repair_media_duplicate_titles(db):
        db.commit()
    result = review_svc.list_candidates(
        db,
        item_type=ItemType.MEDIA_POST,
        category=category,
        platform=platform_key,
        owner_id=_owner_id(request),
        page=page,
        page_size=page_size,
    )
    if (fragment or "").strip().lower() == "items":
        path = request.url.path
        nav = _list_nav(path, result=result, category=category, platform=platform_key)
        return templates.TemplateResponse(
            request,
            "_items_list.html",
            {
                "request": request,
                "items": [present_item(i) for i in result.items],
                "category": category or "",
                "categories": result.categories,
                "page": result.page,
                "page_size": result.page_size,
                "total": result.total,
                "empty_hint": "暂无自媒体条目。请在本页选择平台与关键词后点击「开始抓取」。",
                "platform_tabs": [
                    ("", "全部"),
                    *[(code, label) for code, label in MEDIA_PLATFORMS],
                ],
                "platform_filter": platform_key or "",
                **nav,
            },
        )
    latest = task_manager.latest("collect_media")
    return _page(
        request,
        title="自媒体",
        result=result,
        active="media",
        category=category,
        platform=platform_key,
        template="media.html",
        extra={
            "status": status_dict(settings),
            "platforms": MEDIA_PLATFORMS,
            "selected_platforms": settings.media_platform_list,
            "keywords": ",".join(settings.media_keyword_list),
            "docs_hint": "配置说明见仓库 docs/user-config-media-wechat.md",
            "latest_task": latest.to_dict() if latest else None,
            "empty_hint": "暂无自媒体条目。请在本页选择平台与关键词后点击「开始抓取」。",
            "platform_tabs": [
                ("", "全部"),
                *[(code, label) for code, label in MEDIA_PLATFORMS],
            ],
            "platform_filter": platform_key or "",
        },
    )


@router.get("/releases", response_class=HTMLResponse)
async def releases(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
) -> HTMLResponse:
    result = review_svc.list_candidates(
        db, item_type=ItemType.GITHUB_RELEASE, category=category, page=page, page_size=page_size
    )
    return _page(
        request, title="GitHub Release", result=result, active="releases", category=category
    )


@router.get("/favorites", response_class=HTMLResponse)
async def favorites(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    kind: str | None = Query(None),
    platform: str | None = Query(None),
) -> HTMLResponse:
    from bagel.integrations.mediacrawler import MEDIA_PLATFORMS, PLATFORM_LABELS

    kind_key = (kind or "all").strip().lower()
    kind_map: dict[str, list[str] | None] = {
        "all": None,
        "news": [ItemType.NEWS],
        "github": [ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE],
        "papers": [ItemType.PAPER],
        "stocks": [ItemType.STOCK_NEWS],
        "media": [ItemType.MEDIA_POST],
        "wechat": [ItemType.WECHAT_MSG],
    }
    if kind_key not in kind_map:
        kind_key = "all"
    platform_key = (platform or "").strip().lower() or None
    if kind_key != "media":
        platform_key = None
    elif platform_key and platform_key not in PLATFORM_LABELS:
        platform_key = None
    owner_id = _owner_id(request)
    result = review_svc.list_favorites(
        db,
        category=category,
        item_types=kind_map[kind_key],
        platform=platform_key,
        owner_id=owner_id,
        page=page,
        page_size=page_size,
    )
    extra: dict = {
        "fav_kind": kind_key,
        "fav_kinds": [
            ("all", "全部"),
            ("news", "新闻"),
            ("github", "项目"),
            ("papers", "论文"),
            ("stocks", "股票"),
            ("media", "自媒体"),
            ("wechat", "微信"),
        ],
        "empty_hint": "暂无收藏。可在各列表页点击「收藏」。",
    }
    if kind_key == "media":
        extra["platform_tabs"] = [
            ("", "全部"),
            *[(code, label) for code, label in MEDIA_PLATFORMS],
        ]
        extra["platform_filter"] = platform_key or ""
    return _page(
        request,
        title="已收藏",
        result=result,
        active="favorites",
        category=category,
        kind=kind_key,
        platform=platform_key,
        template="favorites.html",
        extra=extra,
    )


@router.get("/ignored", response_class=HTMLResponse)
async def ignored(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
) -> HTMLResponse:
    result = review_svc.list_ignored(db, category=category, page=page, page_size=page_size)
    return _page(request, title="已忽略", result=result, active="ignored", category=category)


@router.post("/items/{item_id}/action")
async def item_action(
    item_id: UUID,
    action: str = Form(...),
    value: str | None = Form(None),
    next: str = Form("/news"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        if action == "favorite":
            review_svc.favorite(db, item_id, value=True)
        elif action == "unfavorite":
            review_svc.favorite(db, item_id, value=False)
        elif action == "ignore":
            review_svc.ignore(db, item_id)
        elif action == "top":
            review_svc.mark_top(db, item_id, value=True)
        elif action == "untop":
            review_svc.mark_top(db, item_id, value=False)
        elif action == "deep_read":
            review_svc.mark_deep_read(db, item_id, value=True)
        elif action == "undeep_read":
            review_svc.mark_deep_read(db, item_id, value=False)
        elif action == "tag":
            tags = [t.strip() for t in (value or "").split(",") if t.strip()]
            review_svc.add_tags(db, item_id, tags)
        else:
            raise HTTPException(status_code=400, detail=f"未知操作: {action}")
    except review_svc.ReviewError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return RedirectResponse(url=_safe_redirect(next), status_code=303)


_TYPE_LABELS = {
    ItemType.NEWS: "新闻",
    ItemType.PAPER: "论文",
    ItemType.STOCK_NEWS: "股票",
    ItemType.GITHUB_REPO: "GitHub 项目",
    ItemType.GITHUB_RELEASE: "GitHub Release",
    ItemType.MEDIA_POST: "自媒体",
    ItemType.WECHAT_MSG: "微信",
}

_TYPE_BACK = {
    ItemType.NEWS: "/news",
    ItemType.PAPER: "/papers",
    ItemType.STOCK_NEWS: "/stocks",
    ItemType.GITHUB_REPO: "/github",
    ItemType.GITHUB_RELEASE: "/github",
    ItemType.MEDIA_POST: "/media",
    ItemType.WECHAT_MSG: "/wechat",
}


@router.get("/items/{item_id}/related", response_class=HTMLResponse)
async def item_related(
    request: Request,
    item_id: UUID,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    from bagel.services import related as related_svc

    try:
        bundle = related_svc.find_related(db, item_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    seed = bundle.seed
    if not related_svc.supports_related(seed.item_type):
        raise HTTPException(status_code=400, detail="该类型暂不支持关联分析")

    seed_vm = present_item(seed, preview=False)
    groups = []
    for title, hits in bundle.groups:
        groups.append(
            (
                title,
                [
                    {
                        "score": h.score,
                        "reasons": h.reasons,
                        "item": present_item(h.item, preview=False),
                    }
                    for h in hits
                ],
            )
        )

    active_map = {
        ItemType.NEWS: "news",
        ItemType.PAPER: "papers",
        ItemType.STOCK_NEWS: "stocks",
        ItemType.GITHUB_REPO: "github",
        ItemType.GITHUB_RELEASE: "github",
        ItemType.MEDIA_POST: "media",
        ItemType.WECHAT_MSG: "wechat",
    }
    return templates.TemplateResponse(
        request,
        "related.html",
        {
            "title": "关联分析",
            "active": active_map.get(seed.item_type, "news"),
            "nav": NAV_ITEMS,
            "seed": seed_vm,
            "groups": groups,
            "type_label": _TYPE_LABELS.get(seed.item_type, seed.item_type),
            "back_url": _TYPE_BACK.get(seed.item_type, "/news"),
        },
    )


@router.get("/digests", response_class=HTMLResponse)
async def digests_placeholder(request: Request) -> HTMLResponse:
    empty = review_svc.PageResult(items=[], total=0, page=1, page_size=20, categories=[])
    return _page(
        request,
        title="日报 / 周报",
        result=empty,
        active="digests",
        message="日报功能将在 Phase 6 提供。",
    )
