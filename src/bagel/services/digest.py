"""Digest builder — daily markdown + HTML export."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, Region
from bagel.domain.models import IntelItem
from bagel.settings import Settings, get_settings
from bagel.storage.repositories import ItemRepository


@dataclass
class DigestBundle:
    period: str
    title: str
    markdown: str
    html: str
    path_md: Path
    path_html: Path
    item_count: int


def _title(item: IntelItem) -> str:
    return item.llm_title_zh or item.title


def _summary(item: IntelItem) -> str:
    return item.llm_summary or item.summary or ""


def _bullet(item: IntelItem) -> str:
    extra = f"：{_summary(item)}" if _summary(item) else ""
    why = f" — {item.llm_why}" if item.llm_why else ""
    return f"- [{_title(item)}]({item.url}){extra}{why}"


def _is_cn(item: IntelItem) -> bool:
    meta = item.metadata_ or {}
    if meta.get("region") == Region.CN:
        return True
    if item.language in {"zh", "zh-CN", "zh_CN"}:
        return True
    tags = [str(t).lower() for t in (item.tags or [])]
    return any(t in {"cn", "china", "中国", "国内"} for t in tags)


def build_daily_markdown(items: Sequence[IntelItem], *, day: datetime | None = None) -> str:
    day = day or datetime.now(UTC)
    ranked = sorted(items, key=lambda i: (1 if i.is_top else 0, i.score or 0.0), reverse=True)
    top = list(ranked)[:5]

    news = [i for i in items if i.item_type == ItemType.NEWS]
    cn = [i for i in news if _is_cn(i)]
    overseas = [i for i in news if i not in cn]
    repos = [i for i in items if i.item_type == ItemType.GITHUB_REPO]
    releases = [i for i in items if i.item_type == ItemType.GITHUB_RELEASE]
    deep = [i for i in items if i.is_deep_read]

    def section(title: str, rows: list[IntelItem]) -> list[str]:
        return [f"## {title}", *([_bullet(i) for i in rows[:15]] or ["- （暂无）"]), ""]

    lines = [
        f"# 贝果日报（{day.strftime('%Y-%m-%d')}）",
        "",
        "## 今日最重要 5 条",
        *([_bullet(i) for i in top] or ["- （暂无）"]),
        "",
        *section("国内 AI", cn),
        *section("海外 AI", overseas),
        *section("GitHub 新项目", repos),
        *section("GitHub 重要更新", releases),
        *section("深度阅读", deep),
    ]
    return "\n".join(lines)


def markdown_to_simple_html(md: str) -> str:
    parts = [
        "<html><head><meta charset='utf-8'><title>贝果日报</title></head><body>"
    ]
    for line in md.splitlines():
        if line.startswith("# "):
            parts.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            parts.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("- "):
            parts.append(f"<li>{line[2:]}</li>")
        elif not line.strip():
            parts.append("<br/>")
        else:
            parts.append(f"<p>{line}</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def collect_digest_items(session: Session, *, limit: int = 200) -> list[IntelItem]:
    repo = ItemRepository(session)
    selected = list(
        repo.list_by_status(
            [ItemStatus.SELECTED, ItemStatus.SUMMARIZED, ItemStatus.PUBLISHED],
            limit=limit,
        )
    )
    favorites = list(repo.list_favorites(limit=limit))
    by_id = {i.id: i for i in favorites}
    by_id.update({i.id: i for i in selected})
    items = list(by_id.values())
    items.sort(key=lambda i: (1 if i.is_top else 0, i.score or 0.0), reverse=True)
    return items


def write_daily_digest(session: Session, settings: Settings | None = None) -> DigestBundle:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    items = collect_digest_items(session)
    md = build_daily_markdown(items, day=now)
    html = markdown_to_simple_html(md)

    out_dir = Path(settings.data_dir) / "digests"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y-%m-%d")
    path_md = out_dir / f"{stamp}.md"
    path_html = out_dir / f"{stamp}.html"
    path_md.write_text(md, encoding="utf-8")
    path_html.write_text(html, encoding="utf-8")
    return DigestBundle(
        period="daily",
        title=f"贝果日报（{stamp}）",
        markdown=md,
        html=html,
        path_md=path_md,
        path_html=path_html,
        item_count=len(items),
    )
