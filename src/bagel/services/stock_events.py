"""Aggregate stock news into timelines and per-symbol bundles."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType
from bagel.domain.models import IntelItem
from bagel.pipeline.stock_extract import enrich_stock_text, merge_stock_metadata
from bagel.storage.repositories import ItemRepository


@dataclass
class TimelineDay:
    day: str
    count: int
    bullish: int = 0
    bearish: int = 0
    mixed: int = 0
    neutral: int = 0
    items: list[IntelItem] = field(default_factory=list)
    themes: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class SymbolBundle:
    symbol: str
    name: str
    exchange: str
    count: int
    sentiment_counts: dict[str, int]
    themes: list[tuple[str, int]]
    items: list[IntelItem]


def stock_meta(item: IntelItem) -> dict[str, Any]:
    meta = item.metadata_ or {}
    stock = meta.get("stock") if isinstance(meta, dict) else None
    return stock if isinstance(stock, dict) else {}


def ensure_enriched(item: IntelItem) -> dict[str, Any]:
    """Return stock metadata, computing and attaching if missing."""
    existing = stock_meta(item)
    if existing.get("extractor_version") and existing.get("tickers") is not None:
        return existing
    enrichment = enrich_stock_text(item.title or "", item.summary or item.content)
    item.metadata_ = merge_stock_metadata(item.metadata_, enrichment)
    # Prefer finance category over AI taxonomy leftovers.
    if not item.category or item.category in {
        "大模型/LLM",
        "Agent",
        "RAG",
        "多模态",
        "开源发布",
        "推理/训练",
        "机器人/具身",
        "评测/基准",
        "教育应用",
        "行业动态",
        "其他",
    }:
        item.category = enrichment.category
    tags = list(item.tags or [])
    for label in enrichment.tag_labels():
        if label not in tags:
            tags.append(label)
    item.tags = tags[:16]
    return enrichment.as_metadata()


def list_stock_items(
    session: Session,
    *,
    owner_id: UUID | None = None,
    days: int = 14,
    limit: int = 400,
) -> list[IntelItem]:
    repo = ItemRepository(session)
    rows = list(
        repo.list_by_status(
            ItemStatus.CANDIDATE,
            item_type=ItemType.STOCK_NEWS,
            owner_id=owner_id,
            limit=limit,
            offset=0,
        )
    )
    cutoff = datetime.now(UTC) - timedelta(days=max(1, days))
    items: list[IntelItem] = []
    for item in rows:
        ensure_enriched(item)
        pub = item.published_at
        if pub is None:
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=UTC)
        if pub < cutoff:
            continue
        items.append(item)
    items.sort(key=lambda i: i.published_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return items


def build_timeline(items: list[IntelItem]) -> list[TimelineDay]:
    by_day: dict[str, list[IntelItem]] = defaultdict(list)
    for item in items:
        pub = item.published_at
        if pub is None:
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=UTC)
        by_day[pub.date().isoformat()].append(item)

    days: list[TimelineDay] = []
    for day in sorted(by_day.keys(), reverse=True):
        day_items = by_day[day]
        sent = Counter((stock_meta(i).get("sentiment") or "neutral") for i in day_items)
        themes = Counter()
        for i in day_items:
            for th in stock_meta(i).get("themes") or []:
                themes[str(th)] += 1
        days.append(
            TimelineDay(
                day=day,
                count=len(day_items),
                bullish=sent.get("bullish", 0),
                bearish=sent.get("bearish", 0),
                mixed=sent.get("mixed", 0),
                neutral=sent.get("neutral", 0),
                items=day_items[:12],
                themes=themes.most_common(5),
            )
        )
    return days


def build_symbol_index(items: list[IntelItem]) -> list[SymbolBundle]:
    buckets: dict[str, list[IntelItem]] = defaultdict(list)
    names: dict[str, tuple[str, str]] = {}
    for item in items:
        meta = stock_meta(item)
        tickers = meta.get("tickers") or []
        if not tickers:
            continue
        for t in tickers:
            if not isinstance(t, dict):
                continue
            symbol = str(t.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            buckets[symbol].append(item)
            names[symbol] = (str(t.get("name") or symbol), str(t.get("exchange") or "US"))

    out: list[SymbolBundle] = []
    for symbol, bucket in buckets.items():
        sent = Counter((stock_meta(i).get("sentiment") or "neutral") for i in bucket)
        themes = Counter()
        for i in bucket:
            for th in stock_meta(i).get("themes") or []:
                themes[str(th)] += 1
        name, exchange = names.get(symbol, (symbol, "US"))
        out.append(
            SymbolBundle(
                symbol=symbol,
                name=name,
                exchange=exchange,
                count=len(bucket),
                sentiment_counts=dict(sent),
                themes=themes.most_common(6),
                items=sorted(
                    bucket,
                    key=lambda i: i.published_at or datetime.min.replace(tzinfo=UTC),
                    reverse=True,
                )[:30],
            )
        )
    out.sort(key=lambda b: b.count, reverse=True)
    return out


def get_symbol_bundle(items: list[IntelItem], symbol: str) -> SymbolBundle | None:
    key = (symbol or "").strip().upper()
    if not key:
        return None
    for bundle in build_symbol_index(items):
        if bundle.symbol == key:
            return bundle
    return None
