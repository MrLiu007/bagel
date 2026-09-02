"""Parse Feishu / natural-language intel commands and fulfill from DB (+ optional crawl)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType
from bagel.domain.models import IntelItem
from bagel.pipeline.textutil import strip_html, truncate
from bagel.services.feishu_digest import _chunk_text, day_bounds_utc, shanghai_today

logger = logging.getLogger(__name__)
TZ_SH = ZoneInfo("Asia/Shanghai")

_HELP = """【贝果 · 飞书指令】
示例：
· 把8月20号到8月21号的体操方向新闻发我
· 查一下最近的大模型新闻
· 昨日资讯
· 帮助

说明：先查库；若无匹配会自动补采最新新闻后再整理推送（补采未必覆盖你指定的历史区间）。"""

_TYPE_MAP: dict[str, tuple[str, tuple[str, ...]]] = {
    "新闻": ("新闻", (ItemType.NEWS,)),
    "资讯": ("新闻", (ItemType.NEWS,)),
    "消息": ("新闻", (ItemType.NEWS,)),
    "github": ("GitHub", (ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE)),
    "项目": ("GitHub", (ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE)),
    "论文": ("论文", (ItemType.PAPER,)),
    "教育": ("教育", (ItemType.EDUCATION,)),
    "开放课": ("教育", (ItemType.EDUCATION,)),
    "股票": ("股票", (ItemType.STOCK_NEWS,)),
    "自媒体": ("自媒体", (ItemType.MEDIA_POST,)),
    "微信": ("微信", (ItemType.WECHAT_MSG,)),
}

_DATE_RANGE_RE = re.compile(
    r"(?P<m1>\d{1,2})\s*月\s*(?P<d1>\d{1,2})\s*[号日]?"
    r"\s*(?:到|至|-|~|—|–)\s*"
    r"(?P<m2>\d{1,2})\s*月\s*(?P<d2>\d{1,2})\s*[号日]?",
)
_DATE_DOT_RE = re.compile(
    r"(?P<m1>\d{1,2})[./-](?P<d1>\d{1,2})\s*(?:到|至|-|~)\s*(?P<m2>\d{1,2})[./-](?P<d2>\d{1,2})"
)
_MENTION_RE = re.compile(r"@_user_\d+")
_NOISE_RE = re.compile(
    r"(把|将|请|帮我|帮忙|发我|发给我|推送|查一下|查询|看看|整理下|整理一下|"
    r"方向|相关|的|一下|给我|发过来|推给我)"
)


@dataclass
class ParsedCommand:
    kind: str  # help | yesterday | query
    keyword: str = ""
    type_label: str = "新闻"
    item_types: tuple[str, ...] = (ItemType.NEWS,)
    start: date | None = None
    end: date | None = None  # inclusive calendar day
    raw: str = ""


@dataclass
class CommandResult:
    ok: bool
    text: str
    chunks: list[str]
    matched: int = 0
    crawled: bool = False
    crawl_created: int = 0
    parsed: ParsedCommand | None = None


def normalize_text(text: str) -> str:
    t = (text or "").strip()
    t = _MENTION_RE.sub(" ", t)
    t = t.replace("\u200b", "").strip()
    return t


def parse_command(text: str, *, now: datetime | None = None) -> ParsedCommand:
    raw = normalize_text(text)
    lower = raw.lower()
    if not raw or raw in {"帮助", "help", "?", "？", "菜单"}:
        return ParsedCommand(kind="help", raw=raw)
    if "昨日" in raw and ("资讯" in raw or "新闻" in raw or "列表" in raw or raw.strip() == "昨日资讯"):
        return ParsedCommand(kind="yesterday", raw=raw)

    today = shanghai_today(now=now)
    start = end = None
    m = _DATE_RANGE_RE.search(raw) or _DATE_DOT_RE.search(raw)
    work = raw
    if m:
        y = today.year
        start = _safe_date(y, int(m.group("m1")), int(m.group("d1")), today)
        end = _safe_date(y, int(m.group("m2")), int(m.group("d2")), today)
        if start and end and start > end:
            start, end = end, start
        work = (raw[: m.start()] + " " + raw[m.end() :]).strip()

    type_label = "新闻"
    item_types: tuple[str, ...] = (ItemType.NEWS,)
    for token, (label, types) in _TYPE_MAP.items():
        if token.lower() in work.lower():
            type_label = label
            item_types = types
            # remove type token once
            work = re.sub(re.escape(token), " ", work, count=1, flags=re.IGNORECASE)
            break

    kw = _NOISE_RE.sub(" ", work)
    kw = re.sub(r"\s+", " ", kw).strip(" ，,。.!！?？")
    # If still empty and no dates → treat as recent news
    if not kw and start is None:
        # "查新闻" style
        return ParsedCommand(
            kind="query",
            keyword="",
            type_label=type_label,
            item_types=item_types,
            start=today - timedelta(days=1),
            end=today,
            raw=raw,
        )
    if start is None:
        # default: last 3 days including today
        start = today - timedelta(days=2)
        end = today
    if end is None:
        end = start

    return ParsedCommand(
        kind="query",
        keyword=kw,
        type_label=type_label,
        item_types=item_types,
        start=start,
        end=end,
        raw=raw,
    )


def handle_command(session: Session, text: str, *, now: datetime | None = None) -> CommandResult:
    """Query DB; if empty for news queries, collect latest then re-query (latest window)."""
    parsed = parse_command(text, now=now)
    if parsed.kind == "help":
        return CommandResult(ok=True, text=_HELP, chunks=[_HELP], parsed=parsed)

    if parsed.kind == "yesterday":
        from bagel.services.feishu_digest import build_yesterday_digest

        payload = build_yesterday_digest(session, now=now)
        body = "\n\n".join(payload.chunks)
        return CommandResult(
            ok=True,
            text=body,
            chunks=payload.chunks,
            matched=sum(payload.section_counts.values()),
            parsed=parsed,
        )

    assert parsed.start is not None and parsed.end is not None
    start_utc, _ = day_bounds_utc(parsed.start)
    _, end_utc = day_bounds_utc(parsed.end)
    items = search_items(
        session,
        types=parsed.item_types,
        start=start_utc,
        end=end_utc,
        keyword=parsed.keyword,
        limit=20,
    )
    crawled = False
    crawl_created = 0
    note = ""

    if not items and parsed.item_types == (ItemType.NEWS,):
        crawled = True
        try:
            from bagel.jobs.news import run_collect_news

            result = run_collect_news(session)
            crawl_created = int(result.get("items_created") or 0)
            session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("feishu.command.crawl_failed")
            note = f"（补采失败：{exc}）"
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
        else:
            # Re-query requested window first; if still empty, take latest news (any day)
            items = search_items(
                session,
                types=parsed.item_types,
                start=start_utc,
                end=end_utc,
                keyword=parsed.keyword,
                limit=20,
            )
            if not items:
                items = search_items(
                    session,
                    types=parsed.item_types,
                    start=None,
                    end=None,
                    keyword=parsed.keyword,
                    limit=15,
                )
                note = "（库内该时段无匹配，已补采最新并附最近相关）" if items else "（补采后仍无匹配）"
            else:
                note = f"（已补采，新建 {crawl_created} 条）"

    body = format_query_result(parsed, items, note=note)
    try:
        from bagel.services import search_analytics

        search_analytics.log_search(
            session,
            query=parsed.keyword or parsed.raw,
            item_types=parsed.item_types,
            hit_count=len(items),
            channel="feishu",
        )
    except Exception:  # noqa: BLE001
        logger.exception("feishu.command.search_log_failed")
    return CommandResult(
        ok=True,
        text=body,
        chunks=_chunk_text(body),
        matched=len(items),
        crawled=crawled,
        crawl_created=crawl_created,
        parsed=parsed,
    )


def search_items(
    session: Session,
    *,
    types: Sequence[str],
    start: datetime | None,
    end: datetime | None,
    keyword: str = "",
    limit: int = 20,
) -> list[IntelItem]:
    stmt = select(IntelItem).where(
        IntelItem.item_type.in_(list(types)),
        IntelItem.status.in_(
            [
                ItemStatus.CANDIDATE,
                ItemStatus.SELECTED,
                ItemStatus.SUMMARIZED,
                ItemStatus.PUBLISHED,
            ]
        ),
    )
    if start is not None:
        stmt = stmt.where(IntelItem.published_at.is_not(None), IntelItem.published_at >= start)
    if end is not None:
        stmt = stmt.where(IntelItem.published_at.is_not(None), IntelItem.published_at < end)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(
            or_(
                IntelItem.title.ilike(like),
                IntelItem.llm_title_zh.ilike(like),
                IntelItem.summary.ilike(like),
                IntelItem.category.ilike(like),
            )
        )
    stmt = stmt.order_by(IntelItem.published_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())


def format_query_result(
    parsed: ParsedCommand,
    items: list[IntelItem],
    *,
    note: str = "",
) -> str:
    if parsed.start and parsed.end:
        span = (
            f"{parsed.start.isoformat()}"
            if parsed.start == parsed.end
            else f"{parsed.start.isoformat()} ~ {parsed.end.isoformat()}"
        )
    else:
        span = "最近"
    kw = parsed.keyword or "（不限关键词）"
    lines = [
        f"【贝果】{parsed.type_label}查询",
        f"时段：{span}",
        f"关键词：{kw}",
    ]
    if note:
        lines.append(note)
    lines.append("")
    if not items:
        lines.append("暂无匹配条目。可换关键词，或先在系统里配置新闻源后再试。")
    else:
        lines.append(f"共 {len(items)} 条：")
        for item in items:
            title = strip_html(item.llm_title_zh or item.title) or item.title
            when = ""
            if item.published_at:
                when = item.published_at.astimezone(TZ_SH).strftime("%m-%d %H:%M")
            lines.append(f"- [{when}] {truncate(title, 80)}" if when else f"- {truncate(title, 80)}")
            if item.url:
                lines.append(f"  {item.url}")
    return "\n".join(lines).strip()


def _safe_date(year: int, month: int, day: int, today: date) -> date | None:
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    # If date is far in the future vs today, assume previous year
    if d > today + timedelta(days=2):
        try:
            return date(year - 1, month, day)
        except ValueError:
            return d
    return d
