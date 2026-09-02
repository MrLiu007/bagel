"""Optional LLM Wiki export — Markdown files for Obsidian / RAG (not a DB replacement)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from bagel.domain.models import IntelItem, IntelMonthlyBrief
from bagel.settings import Settings, get_settings


def _slug(text: str, limit: int = 48) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", text.strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("-") or "item"
    return cleaned[:limit]


def ensure_wiki_layout(root: Path) -> None:
    for sub in ("news", "github", "media", "wechat", "papers", "education", "models", "briefs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    index = root / "index.md"
    if not index.exists():
        index.write_text(
            "# AI Intel Wiki\n\n由 贝果自动导出。事务数据仍在 SQLite/Postgres。\n",
            encoding="utf-8",
        )


def export_item(item: IntelItem, settings: Settings | None = None) -> Path | None:
    settings = settings or get_settings()
    if not settings.wiki_enabled:
        return None
    root = settings.wiki_path
    ensure_wiki_layout(root)
    bucket = {
        "NEWS": "news",
        "GITHUB_REPO": "github",
        "GITHUB_RELEASE": "github",
        "MEDIA_POST": "media",
        "WECHAT_MSG": "wechat",
        "PAPER": "papers",
        "EDUCATION": "education",
        "MODEL": "models",
    }.get(str(item.item_type), "news")
    month = ""
    if item.published_at is not None:
        month = item.published_at.strftime("%Y-%m")
    else:
        month = datetime.utcnow().strftime("%Y-%m")
    folder = root / bucket / month
    folder.mkdir(parents=True, exist_ok=True)
    fname = f"{_slug(item.title)}-{str(item.id)[:8]}.md"
    path = folder / fname
    tags = ", ".join(str(t) for t in (item.tags or []))
    body = item.llm_summary or item.summary or item.content or ""
    published = item.published_at.isoformat() if item.published_at else ""
    md = (
        f"# {item.title}\n\n"
        f"- type: `{item.item_type}`\n"
        f"- category: `{item.category or ''}`\n"
        f"- published: `{published}`\n"
        f"- url: {item.url}\n"
        f"- tags: {tags}\n\n"
        f"## Summary\n\n{body}\n"
    )
    path.write_text(md, encoding="utf-8")
    return path


def export_monthly_brief(brief: IntelMonthlyBrief, settings: Settings | None = None) -> Path | None:
    settings = settings or get_settings()
    if not settings.wiki_enabled:
        return None
    root = settings.wiki_path
    ensure_wiki_layout(root)
    kind = str(brief.kind).lower()
    path = root / "briefs" / f"{kind}-{brief.year_month}.md"
    title = brief.title or f"{brief.year_month} {kind}"
    content = brief.markdown or ""
    path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
    return path
