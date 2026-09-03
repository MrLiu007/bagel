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
    source_id: str | None = None,
    school: str | None = None,
) -> str:
    params: dict[str, str | int] = {"page": page, "page_size": page_size}
    if category:
        params["category"] = category
    if kind and kind != "all":
        params["kind"] = kind
    if platform:
        params["platform"] = platform
    if source_id:
        params["source_id"] = source_id
    if school:
        params["school"] = school
    return f"{path}?{urlencode(params)}"


def _list_nav(
    path: str,
    *,
    result: review_svc.PageResult,
    category: str | None = None,
    kind: str | None = None,
    platform: str | None = None,
    source_id: str | None = None,
    school: str | None = None,
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
                    page_size=result.page_size,
                    category=category,
                    kind=kind,
                    platform=platform,
                    source_id=source_id,
                    school=school,
                ),
                "active": p == result.page,
            }
        )
    return_url = _page_url(
        path,
        page=result.page,
        page_size=result.page_size,
        category=category,
        kind=kind,
        platform=platform,
        source_id=source_id,
        school=school,
    )
    cat_all_url = _page_url(
        path,
        page=1,
        page_size=result.page_size,
        kind=kind,
        platform=platform,
        source_id=source_id,
        school=school,
    )
    category_urls = {
        c: _page_url(
            path,
            page=1,
            page_size=result.page_size,
            category=c,
            kind=kind,
            platform=platform,
            source_id=source_id,
            school=school,
        )
        for c in result.categories
    }
    prev_url = (
        _page_url(
            path,
            page=result.page - 1,
            page_size=result.page_size,
            category=category,
            kind=kind,
            platform=platform,
            source_id=source_id,
            school=school,
        )
        if result.page > 1
        else None
    )
    next_url = (
        _page_url(
            path,
            page=result.page + 1,
            page_size=result.page_size,
            category=category,
            kind=kind,
            platform=platform,
            source_id=source_id,
            school=school,
        )
        if result.page < total_pages
        else None
    )
    return {
        "base_path": path,
        "return_url": return_url,
        "cat_all_url": cat_all_url,
        "category_urls": category_urls,
        "pages": pages,
        "prev_url": prev_url,
        "next_url": next_url,
        "total_pages": total_pages,
        "kind": kind or "",
        "platform": platform or "",
        "source_id": source_id or "",
        "school": school or "",
    }


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


def _page(
    request: Request,
    *,
    title: str,
    result: review_svc.PageResult,
    active: str,
    category: str | None = None,
    kind: str | None = None,
    platform: str | None = None,
    source_id: str | None = None,
    school: str | None = None,
    message: str | None = None,
    template: str = "items.html",
    extra: dict | None = None,
) -> HTMLResponse:
    path = request.url.path
    nav = _list_nav(
        path,
        result=result,
        category=category,
        kind=kind,
        platform=platform,
        source_id=source_id,
        school=school,
    )
    source_names = (extra or {}).get("source_names") or {}
    ctx: dict = {
        "title": title,
        "items": [
            present_item(
                i,
                source_name=source_names.get(str(getattr(i, "source_id", "") or "")),
            )
            for i in result.items
        ],
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
    source_id: str | None = Query(None, description="Filter by intel_source.id"),
) -> HTMLResponse:
    from bagel.domain.enums import SourceType
    from bagel.domain.enums import ItemStatus
    from bagel.storage.repositories import ItemRepository, SourceRepository

    sid: UUID | None = None
    if source_id:
        try:
            sid = UUID(str(source_id))
        except (TypeError, ValueError):
            sid = None

    owner = _owner_id(request)
    result = review_svc.list_candidates(
        db,
        item_type=ItemType.NEWS,
        category=category,
        source_id=sid,
        owner_id=owner,
        page=page,
        page_size=page_size,
    )

    # Source filter options: sources that already have NEWS candidates, plus all enabled news feeds.
    used_ids = set(
        ItemRepository(db).list_source_ids_for_status(
            ItemStatus.CANDIDATE,
            item_type=ItemType.NEWS,
            owner_id=owner,
        )
    )
    news_types = {SourceType.RSS, SourceType.RSSHUB, SourceType.MANUAL}
    sources = [
        s
        for s in SourceRepository(db).list_all()
        if s.source_type in news_types and (s.enabled or s.id in used_ids)
    ]
    sources.sort(key=lambda s: (0 if s.region == "CN" else 1, s.priority, s.name))
    source_tabs = [("", "全部")] + [(str(s.id), s.name) for s in sources]
    source_names = {str(s.id): s.name for s in sources}
    source_urls = {
        code: _page_url(
            "/news",
            page=1,
            page_size=page_size,
            category=category,
            source_id=code or None,
        )
        for code, _label in source_tabs
    }

    return _page(
        request,
        title="新闻",
        result=result,
        active="news",
        category=category,
        source_id=str(sid) if sid else None,
        extra={
            "source_tabs": source_tabs,
            "source_filter": str(sid) if sid else "",
            "source_urls": source_urls,
            "source_names": source_names,
        },
    )


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


@router.get("/education", response_class=HTMLResponse)
async def education(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    school: str | None = Query(None, description="Institution key, e.g. mit / stanford"),
) -> HTMLResponse:
    from bagel.domain.enums import ItemStatus, SourceType
    from bagel.pipeline.education_orgs import institution_for_source
    from bagel.storage.repositories import ItemRepository, SourceRepository

    owner = _owner_id(request)
    used_ids = set(
        ItemRepository(db).list_source_ids_for_status(
            ItemStatus.CANDIDATE,
            item_type=ItemType.EDUCATION,
            owner_id=owner,
        )
    )
    sources = [
        s
        for s in SourceRepository(db).list_all()
        if s.source_type == SourceType.EDUCATION and (s.enabled or s.id in used_ids)
    ]
    sources.sort(key=lambda s: (s.priority, s.name))
    source_names = {str(s.id): s.name for s in sources}

    # Aggregate feeds into school / institution tabs (MIT OCW + MIT News → MIT).
    buckets: dict[str, dict] = {}
    for s in sources:
        inst = institution_for_source(name=s.name, url=s.url or "")
        bucket = buckets.setdefault(
            inst.key, {"key": inst.key, "label": inst.label, "ids": []}
        )
        bucket["ids"].append(s.id)
    ordered = sorted(buckets.values(), key=lambda b: b["label"].lower())
    school_key = (school or "").strip().lower() or None
    if school_key and school_key not in buckets:
        school_key = None
    filter_ids = buckets[school_key]["ids"] if school_key else None

    result = review_svc.list_candidates(
        db,
        item_type=ItemType.EDUCATION,
        category=category,
        source_ids=filter_ids,
        owner_id=owner,
        page=page,
        page_size=page_size,
    )

    source_tabs = [("", "全部")] + [(b["key"], b["label"]) for b in ordered]
    source_urls = {
        code: _page_url(
            "/education",
            page=1,
            page_size=page_size,
            category=category,
            school=code or None,
        )
        for code, _label in source_tabs
    }

    return _page(
        request,
        title="教育",
        result=result,
        active="education",
        category=category,
        school=school_key,
        extra={
            "source_tabs": source_tabs,
            "source_filter": school_key or "",
            "source_urls": source_urls,
            "source_names": source_names,
            "source_filter_style": "tabs",
            "source_filter_label": "学校",
            "empty_hint": (
                "暂无教育资源。可切换上方学校 Tab（同校多源已聚合），或到采集页拉取；"
                "数据源见系统设置 → 教育数据源。"
            ),
        },
    )


@router.get("/models", response_class=HTMLResponse)
async def models(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    platform: str | None = Query(None),
) -> HTMLResponse:
    from bagel.collectors.models import COMMUNITY_HUGGINGFACE, COMMUNITY_LABELS, COMMUNITY_MODELSCOPE

    community = (platform or "").strip().lower() or None
    if community and community not in COMMUNITY_LABELS:
        community = None
    result = review_svc.list_candidates(
        db,
        item_type=ItemType.MODEL,
        category=category,
        platform=community,
        owner_id=_owner_id(request),
        page=page,
        page_size=page_size,
    )
    return _page(
        request,
        title="模型",
        result=result,
        active="models",
        category=category,
        platform=community,
        extra={
            "empty_hint": "暂无模型条目。",
            "platform_tabs": [
                ("", "全部社区"),
                (COMMUNITY_HUGGINGFACE, COMMUNITY_LABELS[COMMUNITY_HUGGINGFACE]),
                (COMMUNITY_MODELSCOPE, COMMUNITY_LABELS[COMMUNITY_MODELSCOPE]),
            ],
            "platform_filter": community or "",
        },
    )


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
            "empty_hint": "暂无股票资讯。",
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
    kind_key = (kind or "all").strip().lower()
    kind_map: dict[str, list[str] | None] = {
        "all": None,
        "news": [ItemType.NEWS],
        "github": [ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE],
        "papers": [ItemType.PAPER],
        "education": [ItemType.EDUCATION],
        "models": [ItemType.MODEL],
        "stocks": [ItemType.STOCK_NEWS],
        "media": [ItemType.MEDIA_POST],
        "wechat": [ItemType.WECHAT_MSG],
    }
    if kind_key not in kind_map:
        kind_key = "all"
    platform_key = (platform or "").strip().lower() or None
    if kind_key == "media":
        from bagel.integrations.mediacrawler import PLATFORM_LABELS

        if platform_key and platform_key not in PLATFORM_LABELS:
            platform_key = None
    elif kind_key == "models":
        from bagel.collectors.models import COMMUNITY_LABELS

        if platform_key and platform_key not in COMMUNITY_LABELS:
            platform_key = None
    else:
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
            ("education", "教育"),
            ("models", "模型"),
            ("stocks", "股票"),
            ("media", "自媒体"),
            ("wechat", "微信"),
        ],
        "empty_hint": "暂无收藏。可在各列表页点击「收藏」。",
    }
    if kind_key == "media":
        from bagel.integrations.mediacrawler import MEDIA_PLATFORMS

        extra["platform_tabs"] = [
            ("", "全部"),
            *[(code, label) for code, label in MEDIA_PLATFORMS],
        ]
        extra["platform_filter"] = platform_key or ""
    elif kind_key == "models":
        from bagel.collectors.models import COMMUNITY_HUGGINGFACE, COMMUNITY_LABELS, COMMUNITY_MODELSCOPE

        extra["platform_tabs"] = [
            ("", "全部社区"),
            (COMMUNITY_HUGGINGFACE, COMMUNITY_LABELS[COMMUNITY_HUGGINGFACE]),
            (COMMUNITY_MODELSCOPE, COMMUNITY_LABELS[COMMUNITY_MODELSCOPE]),
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
    ItemType.MODEL: "模型",
    ItemType.EDUCATION: "教育",
    ItemType.STOCK_NEWS: "股票",
    ItemType.GITHUB_REPO: "GitHub 项目",
    ItemType.GITHUB_RELEASE: "GitHub Release",
    ItemType.MEDIA_POST: "自媒体",
    ItemType.WECHAT_MSG: "微信",
}

_TYPE_BACK = {
    ItemType.NEWS: "/news",
    ItemType.PAPER: "/papers",
    ItemType.MODEL: "/models",
    ItemType.EDUCATION: "/education",
    ItemType.STOCK_NEWS: "/stocks",
    ItemType.GITHUB_REPO: "/github",
    ItemType.GITHUB_RELEASE: "/github",
    ItemType.MEDIA_POST: "/media",
    ItemType.WECHAT_MSG: "/wechat",
}


@router.get("/api/items/{item_id}/related")
async def item_related_api(
    item_id: UUID,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from bagel.services import related as related_svc
    from bagel.storage.repositories import ItemRepository

    row = ItemRepository(db).get(item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="条目不存在")
    if not related_svc.supports_related(row.item_type):
        raise HTTPException(status_code=400, detail="该类型暂不支持关联分析")
    try:
        payload = related_svc.find_related_drawer(db, item_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    from fastapi.encoders import jsonable_encoder

    return JSONResponse(jsonable_encoder(payload))


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
        ItemType.MODEL: "models",
        ItemType.EDUCATION: "education",
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
