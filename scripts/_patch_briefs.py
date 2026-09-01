"""Patch briefs.py: add /briefs hub, unify active=briefs, redirect generate."""
from __future__ import annotations

from pathlib import Path

path = Path(r"D:\coder\liuzm\new\ai-bagel\src\bagel\web\routes\briefs.py")
text = path.read_text(encoding="utf-8")

# Replace list page active/title section
old_active = '''    active = "briefs_news" if kind == BriefKind.NEWS else "briefs_github"
    title = "新闻总结" if kind == BriefKind.NEWS else "项目总结"
    return templates.TemplateResponse(
        request,
        "briefs.html",
        {
            "title": title,
            "active": active,
            "nav": NAV_ITEMS,
            "kind": kind,
            "kind_path": "news" if kind == BriefKind.NEWS else "github",
            "months": months,
            "current_month": current,
            "brief": brief,
            "article_html": article_html,
            "export_url": f"/briefs/{'news' if kind == BriefKind.NEWS else 'github'}/{current}.md",
        },
    )
'''

# Try both Chinese variants that may exist
variants = [
    old_active,
    old_active.replace("新闻总结", "新闻总结").replace("项目总结", "项目总结"),
]

# Detect by searching for active assignment
import re

m = re.search(
    r'active = "briefs_news".*?export_url": f"/briefs/\{.*?\}/\$\{?current\}?\.md",\s*\},\s*\)',
    text,
    flags=re.S,
)
if not m:
    # simpler replace
    text2 = re.sub(
        r'active = "briefs_news" if kind == BriefKind\.NEWS else "briefs_github"\n\s*title = "[^"]+" if kind == BriefKind\.NEWS else "[^"]+"',
        'active = "briefs"\n    title = "汇总 · 新闻总结" if kind == BriefKind.NEWS else "汇总 · 项目总结"',
        text,
        count=1,
    )
else:
    text2 = text

if text2 == text:
    # manual line-by-line
    lines = text.splitlines(keepends=True)
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if 'active = "briefs_news"' in line:
            out.append('    active = "briefs"\n')
            i += 1
            if i < len(lines) and "title =" in lines[i]:
                out.append(
                    '    title = "汇总 · 新闻总结" if kind == BriefKind.NEWS else "汇总 · 项目总结"\n'
                )
                i += 1
            continue
        out.append(line)
        i += 1
    text2 = "".join(out)

# Insert /briefs redirect before /briefs/news if missing
if '@router.get("/briefs"' not in text2 and '@router.get("/briefs",' not in text2:
    needle = '@router.get("/briefs/news"'
    insert = '''@router.get("/briefs", response_class=HTMLResponse)
async def briefs_hub(
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = Query(None),
) -> HTMLResponse:
    """汇总 tab 默认进入新闻总结。"""
    return _list_page(request, db, BriefKind.NEWS, month)


'''
    if needle in text2:
        text2 = text2.replace(needle, insert + needle, 1)
    else:
        raise SystemExit("cannot find /briefs/news route")

# Redirect generate to /briefs?kind= or keep path but for news use /briefs
text2 = text2.replace(
    'return RedirectResponse(url=f"/briefs/{path}?month={year_month}", status_code=303)',
    'dest = "/briefs" if path == "news" else f"/briefs/{path}"\n'
    '    return RedirectResponse(url=f"{dest}?month={year_month}", status_code=303)',
)

path.write_text(text2, encoding="utf-8")
print("briefs.py patched OK")
