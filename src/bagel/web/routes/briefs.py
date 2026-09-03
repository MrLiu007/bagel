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
from bagel.web.proxy_prefix import app_url
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


def _md_table_cell(text: str) -> str:
    """Table cells: auto-shorten bare URLs so long links cannot blow layout."""
    raw = (text or "").strip()
    if re.match(r"^https?://\S+$", raw, re.I):
        from urllib.parse import urlparse

        try:
            host = (urlparse(raw).netloc or "").removeprefix("www.") or "打开"
        except Exception:  # noqa: BLE001
            host = "打开"
        return f'<a href="{html.escape(raw)}" target="_blank" rel="noopener">{html.escape(host)}</a>'
    return _md_inline(text)


def markdown_to_article_html(md: str) -> str:
    """Lightweight markdown → HTML for sharing preview (not a full parser)."""
    parts: list[str] = []
    in_code = False
    code_lang = ""
    code_buf: list[str] = []
    in_table = False
    list_tag: str | None = None  # "ul" | "ol"

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            parts.append(f"</{list_tag}>")
            list_tag = None

    def open_list(tag: str) -> None:
        nonlocal list_tag
        if list_tag == tag:
            return
        close_list()
        parts.append(f"<{tag}>")
        list_tag = tag

    def flush_code() -> None:
        nonlocal in_code, code_buf, code_lang
        close_list()
        body = "\n".join(code_buf)
        lang = (code_lang or "").strip().lower()
        if lang == "mermaid":
            parts.append(f'<div class="mermaid">{html.escape(body)}</div>')
        else:
            cls = f' class="lang-{html.escape(code_lang)}"' if code_lang else ""
            parts.append(f"<pre><code{cls}>{html.escape(body)}</code></pre>")
        in_code = False
        code_buf = []
        code_lang = ""

    for raw in md.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("```"):
            if in_code:
                flush_code()
            else:
                close_list()
                in_code = True
                code_lang = line[3:].strip()
            continue
        if in_code:
            code_buf.append(line)
            continue

        if line.startswith("|") and "|" in line[1:]:
            close_list()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", ":", " "} for c in cells):
                continue
            if not in_table:
                parts.append('<div class="table-scroll"><table>')
                in_table = True
                parts.append(
                    "<thead><tr>"
                    + "".join(f"<th>{_md_table_cell(c)}</th>" for c in cells)
                    + "</tr></thead><tbody>"
                )
            else:
                parts.append(
                    "<tr>" + "".join(f"<td>{_md_table_cell(c)}</td>" for c in cells) + "</tr>"
                )
            continue
        if in_table:
            parts.append("</tbody></table></div>")
            in_table = False

        if line.startswith("# "):
            close_list()
            parts.append(f"<h1>{_md_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            close_list()
            parts.append(f"<h2>{_md_inline(line[3:])}</h2>")
        elif line.startswith("### "):
            close_list()
            parts.append(f'<h3 class="brief-item-title">{_md_inline(line[4:])}</h3>')
        elif line.startswith("#### "):
            close_list()
            parts.append(f'<h4 class="brief-item-title">{_md_inline(line[5:])}</h4>')
        elif line.startswith("> "):
            close_list()
            parts.append(f"<blockquote>{_md_inline(line[2:])}</blockquote>")
        elif re.match(r"^\*\*〔\s*\d+\s*/\s*\d+\s*〕\*\*$", line.strip()):
            close_list()
            parts.append(f'<p class="item-index">{_md_inline(line.strip().strip("*"))}</p>')
        elif line.startswith("- [ ] ") or line.startswith("- "):
            open_list("ul")
            content = line[6:] if line.startswith("- [ ] ") else line[2:]
            cls = ' class="todo"' if line.startswith("- [ ] ") else ""
            parts.append(f"<li{cls}>{_md_inline(content)}</li>")
        elif line.startswith("---"):
            close_list()
            parts.append('<hr class="item-sep"/>')
        elif not line.strip():
            close_list()
            parts.append("")
        else:
            m = re.match(r"^(\d+)\.\s+(.*)$", line)
            if m:
                open_list("ol")
                parts.append(f"<li>{_md_inline(m.group(2))}</li>")
            else:
                close_list()
                parts.append(f"<p>{_md_inline(line)}</p>")

    if in_code:
        flush_code()
    close_list()
    if in_table:
        parts.append("</tbody></table></div>")
    return "\n".join(parts)


def _resolve_brief(db: Session, *, kind: str, year_month: str):
    """Load brief or generate on demand; return (brief, period_key)."""
    from bagel.services.monthly_templates import TEMPLATE_VERSION

    key = parse_period(year_month, period=period_type_of(year_month))
    brief = brief_svc.get_brief(db, kind=kind, year_month=key)
    needs = brief is None or (brief.template_version or "") != TEMPLATE_VERSION
    if needs:
        bundle = brief_svc.write_monthly_brief(
            db, kind=kind, year_month=key, period=period_type_of(key)
        )
        db.commit()
        brief = bundle.brief
    return brief, key


_PRESENT_CSS = """
@import url("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Source+Sans+3:wght@400;600;700&family=JetBrains+Mono:wght@450&display=swap");

:root {
  --ink: #e7ecef;
  --ink-soft: #b7c2cc;
  --muted: #8a98a6;
  --paper: #12181f;
  --panel: #182129;
  --panel-2: #1e2831;
  --line: rgba(231, 236, 239, 0.10);
  --line-strong: rgba(231, 236, 239, 0.18);
  --accent: #3cb8a5;
  --accent-soft: rgba(60, 184, 165, 0.14);
  --warn: #d4a35c;
  --shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
  --radius: 18px;
  --font-display: "Fraunces", "Source Han Serif SC", "Songti SC", serif;
  --font-body: "Source Sans 3", "PingFang SC", "Microsoft YaHei", sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;
}
@media (prefers-color-scheme: light) {
  :root {
    --ink: #172029;
    --ink-soft: #3a4652;
    --muted: #6b7785;
    --paper: #dfe5ea;
    --panel: #f4f7f9;
    --panel-2: #ebf0f4;
    --line: rgba(23, 32, 41, 0.10);
    --line-strong: rgba(23, 32, 41, 0.16);
    --accent: #1f8f7f;
    --accent-soft: rgba(31, 143, 127, 0.12);
    --warn: #b07d2e;
    --shadow: 0 18px 40px rgba(23, 32, 41, 0.08);
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: var(--font-body);
  color: var(--ink);
  background:
    radial-gradient(900px 420px at 8% -8%, rgba(60,184,165,0.16), transparent 60%),
    radial-gradient(700px 380px at 100% 0%, rgba(212,163,92,0.10), transparent 55%),
    linear-gradient(180deg, color-mix(in srgb, var(--paper) 92%, #000) 0%, var(--paper) 40%, var(--paper) 100%);
  line-height: 1.7;
  min-height: 100vh;
}
.deck-bar {
  position: sticky; top: 0; z-index: 20;
  display: flex; flex-wrap: wrap; gap: 0.45rem; align-items: center;
  padding: 0.7rem 1.15rem;
  background: color-mix(in srgb, var(--paper) 78%, transparent);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(14px) saturate(1.1);
}
.deck-bar a, .deck-bar button {
  appearance: none; border: 1px solid var(--line-strong);
  background: color-mix(in srgb, var(--panel) 88%, transparent);
  color: var(--ink-soft); border-radius: 999px; padding: 0.38rem 0.9rem;
  font-size: 0.84rem; font-weight: 600; text-decoration: none; cursor: pointer;
  letter-spacing: 0.01em;
}
.deck-bar a:hover, .deck-bar button:hover { color: var(--ink); border-color: var(--accent); }
.deck-bar a.primary, .deck-bar button.primary {
  border-color: transparent; background: var(--accent); color: #041512; font-weight: 700;
}
.deck-bar .meta {
  margin-left: auto; color: var(--muted); font-size: 0.8rem;
  font-family: var(--font-mono); max-width: min(42vw, 28rem);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
main.deck {
  width: min(960px, calc(100vw - 1.5rem));
  margin: 0 auto; padding: 1.35rem 0 3.5rem;
}
article.brief-body {
  background:
    linear-gradient(165deg, color-mix(in srgb, var(--panel) 92%, var(--accent)) 0%, var(--panel) 28%, var(--panel) 100%);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: clamp(1.25rem, 2.5vw, 2.1rem) clamp(1.1rem, 2.4vw, 2.2rem) 2.4rem;
  box-shadow: var(--shadow);
  overflow: hidden; /* clip children; tables scroll inside .table-scroll */
}
article.brief-body h1 {
  font-family: var(--font-display);
  font-size: clamp(1.75rem, 3.4vw, 2.35rem);
  font-weight: 700; line-height: 1.22; letter-spacing: -0.02em;
  margin: 0 0 0.85rem; color: var(--ink);
}
article.brief-body h2 {
  font-family: var(--font-display);
  font-size: clamp(1.2rem, 2vw, 1.45rem);
  font-weight: 600; letter-spacing: -0.01em;
  margin: 2.1rem 0 0.85rem; padding: 0 0 0.45rem;
  border-bottom: 1px solid var(--line);
  color: var(--ink);
}
article.brief-body h2::before {
  content: ""; display: inline-block; width: 0.55rem; height: 0.55rem;
  margin-right: 0.55rem; border-radius: 2px; background: var(--accent);
  transform: translateY(-0.08em);
}
article.brief-body h3.brief-item-title, article.brief-body h4.brief-item-title {
  font-family: var(--font-body);
  font-size: 1.06rem; font-weight: 700; line-height: 1.45;
  margin: 0.45rem 0 0.9rem; padding: 0.7rem 0.95rem;
  border-left: 3px solid var(--accent);
  background: linear-gradient(90deg, var(--accent-soft), transparent 80%);
  border-radius: 0 12px 12px 0; color: var(--ink);
}
article.brief-body p, article.brief-body li {
  color: var(--ink-soft); font-size: 1.05rem; max-width: 68ch;
}
article.brief-body strong { color: var(--ink); font-weight: 700; }
article.brief-body ul, article.brief-body ol { padding-left: 1.2rem; margin: 0.45rem 0 0.9rem; }
article.brief-body li + li { margin-top: 0.28rem; }
article.brief-body .item-index {
  margin: 1.75rem 0 0.3rem; color: var(--warn);
  font-weight: 700; font-size: 0.88rem; font-family: var(--font-mono);
  letter-spacing: 0.04em;
}
article.brief-body hr.item-sep {
  border: none; height: 1px; margin: 1.9rem 0 0.7rem;
  background: linear-gradient(90deg, transparent, var(--line-strong), transparent);
}
article.brief-body blockquote {
  margin: 0.75rem 0; padding: 0.75rem 1rem;
  border-left: 3px solid var(--warn);
  color: var(--muted); background: color-mix(in srgb, var(--panel-2) 80%, transparent);
  border-radius: 0 12px 12px 0; font-size: 0.98rem;
}
article.brief-body a {
  color: var(--accent); text-decoration: none; border-bottom: 1px solid color-mix(in srgb, var(--accent) 45%, transparent);
  overflow-wrap: anywhere; word-break: break-word;
}
article.brief-body a:hover { border-bottom-color: var(--accent); }
.table-scroll {
  width: 100%; max-width: 100%;
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  margin: 0.9rem 0 1.1rem;
  border: 1px solid var(--line); border-radius: 14px;
  background: var(--panel-2);
}
article.brief-body table {
  width: 100%; min-width: 0;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: 0.9rem; margin: 0;
}
article.brief-body th, article.brief-body td {
  border-bottom: 1px solid var(--line);
  padding: 0.55rem 0.65rem; text-align: left; vertical-align: top;
  color: var(--ink-soft);
  overflow-wrap: anywhere; word-break: break-word;
}
article.brief-body th {
  background: color-mix(in srgb, var(--panel-2) 70%, var(--accent-soft));
  color: var(--ink); font-weight: 700; font-size: 0.8rem;
  letter-spacing: 0.04em; text-transform: none;
  border-bottom: 1px solid var(--line-strong);
  position: sticky; top: 0;
}
article.brief-body tr:last-child td { border-bottom: none; }
article.brief-body tbody tr:hover td { background: color-mix(in srgb, var(--accent-soft) 55%, transparent); }
/* Link list columns: keep #/date/topic compact; title + link flex */
article.brief-body table th:nth-child(1),
article.brief-body table td:nth-child(1) { width: 2.4rem; }
article.brief-body table th:nth-child(2),
article.brief-body table td:nth-child(2) { width: 5.6rem; white-space: nowrap; }
article.brief-body table th:nth-child(3),
article.brief-body table td:nth-child(3) { width: 6.5rem; }
article.brief-body table th:nth-child(5),
article.brief-body table td:nth-child(5) { width: 7.5rem; }
article.brief-body table td:nth-child(5) a {
  display: inline-block; max-width: 100%;
  font-family: var(--font-mono); font-size: 0.78rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  border-bottom: none; padding: 0.15rem 0.45rem; border-radius: 999px;
  background: var(--accent-soft); color: var(--accent);
}
article.brief-body pre {
  overflow: auto; padding: 0.9rem 1rem; border-radius: 12px;
  border: 1px solid var(--line); background: var(--panel-2);
  font-size: 0.84rem; font-family: var(--font-mono); color: var(--ink-soft);
}
article.brief-body .mermaid {
  margin: 1rem 0; padding: 1rem; border-radius: 14px;
  background: var(--panel-2); border: 1px solid var(--line);
  text-align: center; overflow-x: auto; max-width: 100%;
}
.hint-foot {
  margin-top: 1.15rem; color: var(--muted); font-size: 0.78rem;
  text-align: center; font-family: var(--font-mono); letter-spacing: 0.03em;
}
@media (max-width: 720px) {
  article.brief-body table th:nth-child(3),
  article.brief-body table td:nth-child(3) { display: none; }
  .deck-bar .meta { display: none; }
}
@media print {
  .deck-bar, .hint-foot { display: none !important; }
  body { background: white; color: black; }
  article.brief-body { box-shadow: none; border: none; padding: 0; background: white; overflow: visible; }
  .table-scroll { overflow: visible; border: none; }
}
"""


def _json_str(url: str) -> str:
    import json

    return json.dumps(url)


def build_brief_presentation_html(
    *,
    title: str,
    article_html: str,
    back_url: str,
    export_html_url: str,
    export_md_url: str,
    meta_line: str = "",
    include_chrome: bool = True,
) -> str:
    """Self-contained presentation HTML (online view + download)."""
    bar = ""
    if include_chrome:
        bar = f"""
<header class="deck-bar">
  <a href="{html.escape(back_url)}">← 返回汇总</a>
  <button type="button" onclick="window.print()">打印 / PDF</button>
  <a class="primary" href="{html.escape(export_html_url)}">下载 HTML</a>
  <a href="{html.escape(export_md_url)}">Markdown</a>
  <span class="meta">{html.escape(meta_line)}</span>
</header>"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>{_PRESENT_CSS}</style>
</head>
<body>
{bar}
<main class="deck">
  <article class="brief-body">
{article_html}
  </article>
  <p class="hint-foot">Bagel · 贝果 · 投屏讲解稿 · Esc 返回 · P 打印</p>
</main>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({{ startOnLoad: true, theme: "dark", securityLevel: "loose" }});
</script>
<script>
  document.addEventListener("keydown", (e) => {{
    if (e.key === "p" || e.key === "P") {{ if (!e.metaKey && !e.ctrlKey) window.print(); }}
    if (e.key === "Escape") {{ location.href = {_json_str(back_url)}; }}
  }});
</script>
</body>
</html>"""


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
            "export_html_url": f"/briefs/{kind_path}/{current}.html",
            "present_url": f"/briefs/{kind_path}/{current}/present",
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


@router.get("/briefs/{kind_path}/{year_month}/present", response_class=HTMLResponse)
async def present_brief(
    request: Request,
    kind_path: str,
    year_month: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    kind = _kind_or_404(kind_path)
    brief, key = _resolve_brief(db, kind=kind, year_month=year_month)
    path, _title = _KIND_UI[kind]
    list_url = "/briefs" if kind == BriefKind.NEWS else f"/briefs/{path}"
    back = f"{list_url}?month={key}&period={period_type_of(key)}"
    article = markdown_to_article_html(brief.markdown or "")
    meta = f"{brief.title} · {brief.item_count} 条"
    if brief.generated_at:
        meta += f" · {brief.generated_at}"
    doc = build_brief_presentation_html(
        title=brief.title or f"汇总 {key}",
        article_html=article,
        back_url=app_url(request, back),
        export_html_url=app_url(request, f"/briefs/{path}/{key}.html"),
        export_md_url=app_url(request, f"/briefs/{path}/{key}.md"),
        meta_line=meta,
        include_chrome=True,
    )
    return HTMLResponse(doc)


@router.get("/briefs/{kind_path}/{year_month}.html", response_class=HTMLResponse)
async def export_html(
    request: Request,
    kind_path: str,
    year_month: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    kind = _kind_or_404(kind_path)
    brief, key = _resolve_brief(db, kind=kind, year_month=year_month)
    path, _ = _KIND_UI[kind]
    list_url = "/briefs" if kind == BriefKind.NEWS else f"/briefs/{path}"
    back = f"{list_url}?month={key}&period={period_type_of(key)}"
    article = markdown_to_article_html(brief.markdown or "")
    doc = build_brief_presentation_html(
        title=brief.title or f"汇总 {key}",
        article_html=article,
        back_url=app_url(request, back),
        export_html_url=app_url(request, f"/briefs/{path}/{key}.html"),
        export_md_url=app_url(request, f"/briefs/{path}/{key}.md"),
        meta_line=f"{brief.title} · {brief.item_count} 条",
        include_chrome=True,
    )
    filename = f"{key}-{kind.lower()}.html"
    return HTMLResponse(
        doc,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/briefs/{kind_path}/{year_month}.md", response_class=PlainTextResponse)
async def export_markdown(
    kind_path: str,
    year_month: str,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    kind = _kind_or_404(kind_path)
    brief, key = _resolve_brief(db, kind=kind, year_month=year_month)
    filename = f"{key}-{kind.lower()}.md"
    return PlainTextResponse(
        brief.markdown or "",
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
