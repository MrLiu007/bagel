"""Search event logging and dashboard aggregates."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType
from bagel.domain.models import IntelItem, IntelSearchEvent, IntelSource

_NOISE = re.compile(
    r"(把|将|请|帮我|查一下|查询|看看|发我|推送|的|一下|给我|新闻|资讯|项目|论文|股票|模型|自媒体|微信)",
    re.I,
)
_TYPE_LABELS: dict[str, str] = {
    ItemType.NEWS: "新闻",
    ItemType.GITHUB_REPO: "GitHub 项目",
    ItemType.GITHUB_RELEASE: "GitHub Release",
    ItemType.PAPER: "论文",
    ItemType.EDUCATION: "教育",
    ItemType.MODEL: "模型",
    ItemType.STOCK_NEWS: "股票",
    ItemType.MEDIA_POST: "自媒体",
    ItemType.WECHAT_MSG: "微信",
}


def normalize_query(raw: str) -> str:
    text = (raw or "").strip()
    text = _NOISE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:255]


def log_search(
    session: Session,
    *,
    query: str,
    item_types: tuple[str, ...] | list[str],
    hit_count: int,
    channel: str = "web",
    owner_id: UUID | None = None,
) -> IntelSearchEvent | None:
    cleaned = normalize_query(query)
    if not cleaned or len(cleaned) < 2:
        return None
    types_csv = ",".join(sorted({str(t) for t in item_types if t}))
    row = IntelSearchEvent(
        query=cleaned,
        item_types=types_csv,
        hit_count=max(0, int(hit_count)),
        channel=(channel or "web")[:32],
        owner_id=owner_id,
    )
    session.add(row)
    session.flush()
    return row


def search_count(session: Session, *, owner_id: UUID | None = None, days: int = 90) -> int:
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = select(func.count()).select_from(IntelSearchEvent).where(
        IntelSearchEvent.created_at >= since
    )
    if owner_id is not None:
        stmt = stmt.where(IntelSearchEvent.owner_id == owner_id)
    return int(session.scalar(stmt) or 0)


def keyword_rankings(
    session: Session,
    *,
    owner_id: UUID | None = None,
    limit: int = 20,
    days: int = 90,
) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(
            IntelSearchEvent.query,
            func.count().label("cnt"),
            func.sum(IntelSearchEvent.hit_count).label("hits"),
        )
        .where(IntelSearchEvent.created_at >= since)
        .group_by(IntelSearchEvent.query)
        .order_by(func.count().desc())
        .limit(limit)
    )
    if owner_id is not None:
        stmt = stmt.where(IntelSearchEvent.owner_id == owner_id)
    rows = session.execute(stmt).all()
    return [
        {"keyword": r.query, "searches": int(r.cnt), "hits": int(r.hits or 0)}
        for r in rows
    ]


def item_type_stats(session: Session, *, days: int = 90) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = session.execute(
        select(IntelItem.item_type, func.count())
        .where(
            IntelItem.status != ItemStatus.REJECTED,
            IntelItem.published_at.is_not(None),
            IntelItem.published_at >= since,
        )
        .group_by(IntelItem.item_type)
        .order_by(func.count().desc())
    ).all()
    return [
        {
            "type": t,
            "label": _TYPE_LABELS.get(t, t),
            "count": int(c),
        }
        for t, c in rows
    ]


def source_stats(session: Session, *, limit: int = 15, days: int = 90) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = session.execute(
        select(IntelSource.name, func.count())
        .join(IntelItem, IntelItem.source_id == IntelSource.id)
        .where(
            IntelItem.status != ItemStatus.REJECTED,
            IntelItem.published_at.is_not(None),
            IntelItem.published_at >= since,
        )
        .group_by(IntelSource.name)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return [{"name": name, "count": int(cnt)} for name, cnt in rows]


def aggregate_search_keywords(
    session: Session,
    *,
    min_count: int = 2,
    days: int = 30,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Grouped search queries for keyword self-growth job."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = session.execute(
        select(
            IntelSearchEvent.query,
            IntelSearchEvent.item_types,
            func.count().label("cnt"),
        )
        .where(IntelSearchEvent.created_at >= since)
        .group_by(IntelSearchEvent.query, IntelSearchEvent.item_types)
        .having(func.count() >= min_count)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    out: list[dict[str, Any]] = []
    for query, types_csv, cnt in rows:
        types = [t.strip() for t in (types_csv or "").split(",") if t.strip()]
        out.append({"query": query, "item_types": types, "count": int(cnt)})
    return out
