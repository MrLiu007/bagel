"""Monthly / weekly brief pages — 新闻总结 / 项目总结 / 论文总结 / 自媒体总结."""

from __future__ import annotations

import html
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from bagel.domain.enums import BriefKind
from bagel.services import monthly_brief as brief_svc
from bagel.services import brief_prompts
from bagel.services import search_analytics
from bagel.services.gbrain import dashboard_payload
from bagel.services.feishu_command import search_items
from bagel.services.monthly_brief import (
    format_period_option,
    list_available_periods,
    parse_period,
    period_type_of,
    scope_label,
)
from bagel.storage.database import get_db
from bagel.web.nav import NAV_ITEMS
from bagel.web.templating import templates

router = APIRouter(tags=["briefs"])


def _owner_id(request: Request):
    raw = request.session.get("user_id")
    if not raw:
        return None
    try:
        from uuid import UUID

        return UUID(str(raw))
    except ValueError:
        return None


_KIND_UI: dict[str, tuple[str, str]] = {
    BriefKind.NEWS: ("news", "汇总 · 新闻总结"),
    BriefKind.GITHUB: ("github", "汇总 · 项目总结"),
    BriefKind.SCIENCE: ("papers", "汇总 · 论文总结"),
    BriefKind.EDUCATION: ("education", "汇总 · 教育总结"),
    BriefKind.MODEL: ("models", "汇总 · 模型总结"),
    BriefKind.MEDIA: ("media", "汇总 · 自媒体总结"),
    BriefKind.STOCK: ("stocks", "汇总 · 股票总结"),
}

_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_CODE = re.compile(r"`([^`]+)`")


def _kind_or_404(kind: str) -> str:
    key = kind.upper()
    if key == "NEWS":
        return BriefKind.NEWS
    if key in {"GITHUB", "PROJECT", "PROJECTS"}:
        return BriefKind.GITHUB
    if key in {"SCIENCE", "PAPER", "PAPERS"}:
        return BriefKind.SCIENCE
    if key in {"EDUCATION", "EDU", "COURSE", "COURSES"}:
        return BriefKind.EDUCATION
    if key in {"MODEL", "MODELS"}:
        return BriefKind.MODEL
    if key in {"MEDIA", "MEDIA_POST"}:
        return BriefKind.MEDIA
    if key in {"STOCK", "STOCKS", "STOCK_NEWS"}:
        return BriefKind.STOCK
    raise HTTPException(status_code=404, detail="未知总结类型")


def _period_or_default(period: str | None) -> str:
    p = (period or "month").strip().lower()
    return "week" if p == "week" else "month"


def _md_inline(text: str) -> str:
    text = html.escape(text)
    text = _MD_LINK.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    text = _MD_BOLD.sub(r"<strong>\1</strong>", text)
    text = _MD_CODE.sub(r"<code>\1</code>", text)
    return text


def markdown_to_article_html(md: str) -> str:
    """Lightweight markdown → HTML for sharing preview (not a full parser)."""
    parts: list[str] = []
    in_code = False
    code_lang = ""
    code_buf: list[str] = []
    in_table = False

    def flush_code() -> None:
        nonlocal in_code, code_buf, code_lang
        body = html.escape("\n".join(code_buf))
        cls = f' class="lang-{html.escape(code_lang)}"' if code_lang else ""
        parts.append(f"<pre><code{cls}>{body}</code></pre>")
        in_code = False
        code_buf = []
        code_lang = ""

    for raw in md.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("```"):
            if in_code:
                flush_code()
            else:
                in_code = True
                code_lang = line[3:].strip()
            continue
        if in_code:
            code_buf.append(line)
            continue

        if line.startswith("|") and "|" in line[1:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", ":", " "} for c in cells):
                continue
            if not in_table:
                parts.append("<table>")
                in_table = True
                parts.append(
                    "<thead><tr>"
                    + "".join(f"<th>{_md_inline(c)}</th>" for c in cells)
                    + "</tr></thead><tbody>"
                )
            else:
                parts.append(
                    "<tr>" + "".join(f"<td>{_md_inline(c)}</td>" for c in cells) + "</tr>"
                )
            continue
        if in_table:
            parts.append("</tbody></table>")
            in_table = False

        if line.startswith("# "):
            parts.append(f"<h1>{_md_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            parts.append(f"<h2>{_md_inline(line[3:])}</h2>")
        elif line.startswith("### "):
            parts.append(f'<h3 class="brief-item-title">{_md_inline(line[4:])}</h3>')
        elif line.startswith("#### "):
            parts.append(f'<h4 class="brief-item-title">{_md_inline(line[5:])}</h4>')
        elif line.startswith("> "):
            parts.append(f'<blockquote>{_md_inline(line[2:])}</blockquote>')
        elif re.match(r"^\*\*〔\s*\d+\s*/\s*\d+\s*〕\*\*$", line.strip()):
            parts.append(f'<p class="item-index">{_md_inline(line.strip().strip("*"))}</p>')
        elif line.startswith("- [ ] "):
            parts.append(f"<li class='todo'>{_md_inline(line[6:])}</li>")
        elif line.startswith("- "):
            parts.append(f"<li>{_md_inline(line[2:])}</li>")
        elif line.startswith("---"):
            parts.append('<hr class="item-sep"/>')
        elif not line.strip():
            parts.append("")
        else:
            m = re.match(r"^(\d+)\.\s+(.*)$", line)
            if m:
                parts.append(f"<li>{_md_inline(m.group(2))}</li>")
            else:
                parts.append(f"<p>{_md_inline(line)}</p>")

    if in_code:
        flush_code()
    if in_table:
        parts.append("</tbody></table>")
    return "\n".join(parts)


@router.get("/briefs/dashboard", response_class=HTMLResponse)
async def briefs_dashboard_redirect() -> RedirectResponse:
    return RedirectResponse(url="/briefs/space", status_code=301)


@router.get("/briefs/space", response_class=HTMLResponse)
async def briefs_space(
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = Query(None),
    seed: str | None = Query(None),
    view: str | None = Query("board"),
) -> HTMLResponse:
    oid = _owner_id(request)
    space_view = "graph" if (view or "").lower() in {"graph", "gbrain", "kg"} else "board"
    if seed:
        space_view = "graph"
    search_note = None
    if q and q.strip():
        from bagel.domain.enums import ItemType

        types = (
            ItemType.NEWS,
            ItemType.GITHUB_REPO,
            ItemType.PAPER,
            ItemType.EDUCATION,
            ItemType.MODEL,
            ItemType.STOCK_NEWS,
            ItemType.MEDIA_POST,
            ItemType.WECHAT_MSG,
        )
        items = search_items(db, types=types, start=None, end=None, keyword=q.strip(), limit=8)
        search_analytics.log_search(
            db,
            query=q,
            item_types=types,
            hit_count=len(items),
            channel="space",
            owner_id=oid,
        )
        db.commit()
        search_note = f"已记录搜索「{q.strip()}」，命中 {len(items)} 条"
    stats = dashboard_payload(db, owner_id=oid)
    if seed:
        try:
            from uuid import UUID

            from bagel.services.gbrain import build_knowledge_graph

            graph = build_knowledge_graph(db, seed_id=UUID(seed))
            stats = {**stats, "echarts": graph.echarts}
        except Exception:
            pass
    return templates.TemplateResponse(
        request,
        "briefs_dashboard.html",
        {
            "title": "汇总 · 个人空间",
            "active": "briefs",
            "nav": NAV_ITEMS,
            "kind": "SPACE",
            "kind_path": "space",
            "list_url": "/briefs/space",
            "period": "month",
            "current_month": "",
            "stats": stats,
            "search_note": search_note,
            "search_q": q or "",
            "space_view": space_view,
        },
    )


@router.get("/briefs", response_class=HTMLResponse)
async def briefs_hub(
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = Query(None),
    period: str | None = Query(None),
) -> HTMLResponse:
    """汇总 tab：默认展示新闻总结。"""
    return _list_page(request, db, BriefKind.NEWS, month, period)


@router.get("/briefs/news", response_class=HTMLResponse)
async def briefs_news(
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = Query(None),
    period: str | None = Query(None),
) -> HTMLResponse:
    return _list_page(request, db, BriefKind.NEWS, month, period)


@router.get("/briefs/github", response_class=HTMLResponse)
async def briefs_github(
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = Query(None),
    period: str | None = Query(None),
) -> HTMLResponse:
    return _list_page(request, db, BriefKind.GITHUB, month, period)


@router.get("/briefs/papers", response_class=HTMLResponse)
async def briefs_papers(
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = Query(None),
    period: str | None = Query(None),
) -> HTMLResponse:
    return _list_page(request, db, BriefKind.SCIENCE, month, period)


@router.get("/briefs/education", response_class=HTMLResponse)
async def briefs_education(
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = Query(None),
    period: str | None = Query(None),
) -> HTMLResponse:
    return _list_page(request, db, BriefKind.EDUCATION, month, period)


@router.get("/briefs/models", response_class=HTMLResponse)
async def briefs_models(
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = Query(None),
    period: str | None = Query(None),
) -> HTMLResponse:
    return _list_page(request, db, BriefKind.MODEL, month, period)


@router.get("/briefs/science", response_class=HTMLResponse)
async def briefs_science_redirect(
    month: str | None = Query(None),
    period: str | None = Query(None),
) -> RedirectResponse:
    qs = []
    if month:
        qs.append(f"month={month}")
    if period:
        qs.append(f"period={period}")
    suffix = ("?" + "&".join(qs)) if qs else ""
    return RedirectResponse(url=f"/briefs/papers{suffix}", status_code=301)


@router.get("/briefs/media", response_class=HTMLResponse)
async def briefs_media(
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = Query(None),
    period: str | None = Query(None),
) -> HTMLResponse:
    return _list_page(request, db, BriefKind.MEDIA, month, period)


@router.get("/briefs/stocks", response_class=HTMLResponse)
async def briefs_stocks(
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = Query(None),
    period: str | None = Query(None),
) -> HTMLResponse:
    return _list_page(request, db, BriefKind.STOCK, month, period)


def _list_page(
    request: Request,
    db: Session,
    kind: str,
    month: str | None,
    period: str | None,
) -> HTMLResponse:
    period_key_type = _period_or_default(period)
    if month and period_type_of(month) == "week":
        period_key_type = "week"
    periods = list_available_periods(db, kind=kind, period=period_key_type)
    current = month or (periods[0] if periods else parse_period(period=period_key_type))
    try:
        current = parse_period(current, period=period_key_type)
    except ValueError:
        current = parse_period(period=period_key_type)
    from bagel.services.monthly_templates import TEMPLATE_VERSION

    brief = brief_svc.get_brief(db, kind=kind, year_month=current)
    # Refresh manuscripts generated by older question-heavy templates.
    if brief is not None and (brief.template_version or "") != TEMPLATE_VERSION:
        try:
            bundle = brief_svc.write_monthly_brief(
                db, kind=kind, year_month=current, period=period_key_type
            )
            db.commit()
            brief = bundle.brief
        except Exception:
            db.rollback()
    article_html = markdown_to_article_html(brief.markdown) if brief else ""
    kind_path, title = _KIND_UI[kind]
    list_url = "/briefs" if kind == BriefKind.NEWS else f"/briefs/{kind_path}"
    scope = scope_label(period_key_type)
    period_options = [{"value": p, "label": format_period_option(p)} for p in periods]
    if current not in periods:
        period_options.insert(0, {"value": current, "label": format_period_option(current)})
    default_prompt = brief_prompts.load_default(kind)
    prompt_used = ""
    if brief and brief.metadata_:
        prompt_used = str(brief.metadata_.get("prompt_used") or "")
    return templates.TemplateResponse(
        request,
        "briefs.html",
        {
            "title": title,
            "active": "briefs",
            "nav": NAV_ITEMS,
            "kind": kind,
            "kind_path": kind_path,
            "list_url": list_url,
            "months": periods,
            "period_options": period_options,
            "current_month": current,
            "period": period_key_type,
            "scope_label": scope,
            "cadence_label": "周总结" if period_key_type == "week" else "月总结",
            "brief": brief,
            "article_html": article_html,
            "export_url": f"/briefs/{kind_path}/{current}.md",
            "default_prompt": default_prompt,
            "prompt_used": prompt_used,
        },
    )


@router.post("/briefs/generate")
async def generate_brief(
    kind: str = Form(...),
    year_month: str = Form(...),
    period: str = Form("month"),
    custom_prompt: str = Form(""),
    save_prompt_default: str = Form("0"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    resolved = _kind_or_404(kind)
    period_key_type = _period_or_default(period)
    try:
        key = parse_period(year_month, period=period_key_type)
        brief_svc.write_monthly_brief(
            db,
            kind=resolved,
            year_month=key,
            period=period_key_type,
            custom_prompt=custom_prompt or None,
            save_prompt_default=save_prompt_default in {"1", "true", "on"},
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if resolved == BriefKind.NEWS:
        return RedirectResponse(
            url=f"/briefs?month={key}&period={period_key_type}", status_code=303
        )
    kind_path, _ = _KIND_UI[resolved]
    return RedirectResponse(
        url=f"/briefs/{kind_path}?month={key}&period={period_key_type}", status_code=303
    )


@router.get("/api/gbrain/card")
async def api_gbrain_card(
    request: Request,
    db: Session = Depends(get_db),
    key: str = Query(..., min_length=3, max_length=160),
) -> JSONResponse:
    from bagel.services.gbrain_learn import knowledge_card, record_learn

    card = knowledge_card(db, key)
    if card is None:
        raise HTTPException(status_code=404, detail="知识点不存在")
    oid = _owner_id(request)
    try:
        record_learn(db, node_key=key, action="view", owner_id=oid)
        db.commit()
    except Exception:
        db.rollback()
    return JSONResponse(card)


@router.post("/api/gbrain/learn")
async def api_gbrain_learn(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    from bagel.services.gbrain_learn import record_learn

    body = await request.json()
    key = str(body.get("key") or "").strip()
    action = str(body.get("action") or "focus").strip() or "focus"
    if not key:
        raise HTTPException(status_code=400, detail="缺少 key")
    oid = _owner_id(request)
    record_learn(db, node_key=key, action=action, owner_id=oid, metadata={"via": "space"})
    db.commit()
    return JSONResponse({"ok": True, "key": key, "action": action})


@router.get("/api/gbrain/review")
async def api_gbrain_review(
    request: Request,
    db: Session = Depends(get_db),
    days: int = Query(14, ge=1, le=90),
) -> JSONResponse:
    from bagel.services.gbrain_learn import review_summary

    try:
        data = review_summary(db, owner_id=_owner_id(request), days=days)
    except Exception:
        # Degraded when migration not applied.
        db.rollback()
        data = {
            "days": days,
            "event_count": 0,
            "unique_nodes": 0,
            "recent": [],
            "hot": [],
            "suggestions": [],
            "degraded": True,
        }
    return JSONResponse(data)


@router.get("/briefs/{kind_path}/{year_month}.md", response_class=PlainTextResponse)
async def export_markdown(
    kind_path: str,
    year_month: str,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    kind = _kind_or_404(kind_path)
    key = parse_period(year_month, period=period_type_of(year_month))
    brief = brief_svc.get_brief(db, kind=kind, year_month=key)
    if brief is None:
        bundle = brief_svc.write_monthly_brief(
            db, kind=kind, year_month=key, period=period_type_of(key)
        )
        db.commit()
        body = bundle.markdown
        filename = f"{key}-{kind.lower()}.md"
    else:
        body = brief.markdown
        filename = f"{key}-{kind.lower()}.md"
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
