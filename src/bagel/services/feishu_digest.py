"""Build Feishu-ready digests from local intel DB (lists + weekly briefs)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.domain.enums import BriefKind, ItemStatus, ItemType
from bagel.domain.models import IntelItem
from bagel.pipeline.textutil import strip_html, truncate
from bagel.services.monthly_brief import get_brief, parse_year_week

TZ_SH = ZoneInfo("Asia/Shanghai")

# Feishu custom bot text soft limit — keep margin for framing.
_CHUNK_CHARS = 3500

_TYPE_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("新闻", "news", (ItemType.NEWS,)),
    ("GitHub项目", "github", (ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE)),
    ("论文", "papers", (ItemType.PAPER,)),
    ("教育", "education", (ItemType.EDUCATION,)),
    ("模型", "models", (ItemType.MODEL,)),
    ("股票", "stocks", (ItemType.STOCK_NEWS,)),
    ("自媒体", "media", (ItemType.MEDIA_POST,)),
    ("微信", "wechat", (ItemType.WECHAT_MSG,)),
)

_BRIEF_KINDS: tuple[tuple[str, str], ...] = (
    ("新闻总结", BriefKind.NEWS),
    ("项目总结", BriefKind.GITHUB),
    ("论文总结", BriefKind.SCIENCE),
    ("教育总结", BriefKind.EDUCATION),
    ("模型总结", BriefKind.MODEL),
    ("股票总结", BriefKind.STOCK),
    ("自媒体总结", BriefKind.MEDIA),
)


@dataclass
class DigestPayload:
    title: str
    chunks: list[str]
    section_counts: dict[str, int]


def shanghai_today(*, now: datetime | None = None) -> date:
    now = now or datetime.now(UTC)
    return now.astimezone(TZ_SH).date()


def day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start_local = datetime(day.year, day.month, day.day, tzinfo=TZ_SH)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def build_yesterday_digest(
    session: Session,
    *,
    per_type_limit: int = 8,
    now: datetime | None = None,
) -> DigestPayload:
    day = shanghai_today(now=now) - timedelta(days=1)
    start, end = day_bounds_utc(day)
    lines: list[str] = [
        f"【贝果】昨日资讯（{day.isoformat()}）",
        "",
    ]
    counts: dict[str, int] = {}
    for label, _key, types in _TYPE_SPECS:
        items = _list_items(session, types=types, start=start, end=end, limit=per_type_limit)
        counts[label] = len(items)
        lines.append(f"## {label}（{len(items)}）")
        if not items:
            lines.append("- （暂无）")
        else:
            for item in items:
                title = strip_html(item.llm_title_zh or item.title) or item.title
                lines.append(f"- {truncate(title, 80)}")
                if item.url:
                    lines.append(f"  {item.url}")
        lines.append("")
    body = "\n".join(lines).strip()
    return DigestPayload(
        title=f"昨日资讯 {day.isoformat()}",
        chunks=_chunk_text(body),
        section_counts=counts,
    )


def build_week_briefs_digest(
    session: Session,
    *,
    which: str = "this",  # this | last | both
    now: datetime | None = None,
    max_chars_per_brief: int = 900,
) -> DigestPayload:
    now = now or datetime.now(UTC)
    this_key = parse_year_week(None, now=now)
    last_dt = now - timedelta(days=7)
    last_key = parse_year_week(None, now=last_dt)
    keys: list[tuple[str, str]] = []
    if which in {"this", "both"}:
        keys.append(("本周", this_key))
    if which in {"last", "both"}:
        keys.append(("上周", last_key))

    lines: list[str] = ["【贝果】周汇总快照", ""]
    counts: dict[str, int] = {}
    for scope, period_key in keys:
        lines.append(f"# {scope}（{period_key}）")
        lines.append("")
        for label, kind in _BRIEF_KINDS:
            brief = get_brief(session, kind=kind, year_month=period_key)
            key = f"{scope}-{label}"
            if brief is None or not (brief.markdown or "").strip():
                counts[key] = 0
                lines.append(f"## {label}")
                lines.append("- （尚未生成，可在「汇总」页生成周总结）")
                lines.append("")
                continue
            counts[key] = 1
            excerpt = _brief_excerpt(brief.markdown, limit=max_chars_per_brief)
            lines.append(f"## {label}")
            lines.append(excerpt)
            lines.append("")
    body = "\n".join(lines).strip()
    return DigestPayload(
        title="周汇总快照",
        chunks=_chunk_text(body),
        section_counts=counts,
    )


def _list_items(
    session: Session,
    *,
    types: Sequence[str],
    start: datetime,
    end: datetime,
    limit: int,
) -> list[IntelItem]:
    stmt = (
        select(IntelItem)
        .where(
            IntelItem.item_type.in_(list(types)),
            IntelItem.status.in_(
                [
                    ItemStatus.CANDIDATE,
                    ItemStatus.SELECTED,
                    ItemStatus.SUMMARIZED,
                    ItemStatus.PUBLISHED,
                ]
            ),
            IntelItem.published_at.is_not(None),
            IntelItem.published_at >= start,
            IntelItem.published_at < end,
        )
        .order_by(IntelItem.published_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def _brief_excerpt(md: str, *, limit: int) -> str:
    text = (md or "").strip()
    # Drop mermaid blocks to keep Feishu readable
    out: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        out.append(line)
    cleaned = "\n".join(out).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _chunk_text(text: str, *, size: int = _CHUNK_CHARS) -> list[str]:
    text = (text or "").strip()
    if not text:
        return ["（空）"]
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    cur = 0
    for line in text.splitlines(keepends=True):
        if cur + len(line) > size and buf:
            chunks.append("".join(buf).rstrip())
            buf = [line]
            cur = len(line)
        else:
            buf.append(line)
            cur += len(line)
    if buf:
        chunks.append("".join(buf).rstrip())
    # Cap to avoid spamming the chat
    if len(chunks) > 6:
        head = chunks[:5]
        head.append(chunks[5][: size - 40] + "\n…（后续已截断）")
        return head
    return chunks
