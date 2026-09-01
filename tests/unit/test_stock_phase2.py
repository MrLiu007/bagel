"""Tests for stock enrichment + stock brief template."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from bagel.domain.enums import BriefKind, ItemStatus, ItemType, SourceType
from bagel.domain.models import Base
from bagel.pipeline.stock_extract import enrich_stock_text
from bagel.services.monthly_templates import render_monthly_brief
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.repositories import ItemRepository


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'stock.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def test_enrich_nvda_bullish():
    e = enrich_stock_text("NVDA shares surge after earnings beat", "AI chip demand")
    assert any(t.symbol == "NVDA" for t in e.tickers)
    assert e.sentiment == "bullish"
    assert e.category in {"财报业绩", "个股动态", "板块轮动", "其他"}


def test_enrich_cn_alias():
    e = enrich_stock_text("贵州茅台股价波动", "白酒板块情绪回暖")
    assert any(t.symbol.endswith(".SS") for t in e.tickers)
    assert "板块轮动" in e.themes or e.category in {"板块轮动", "个股动态", "市场情绪", "其他"}


def test_stock_brief_has_disclaimer(db: Session):
    repo = ItemRepository(db)
    item, _ = repo.upsert_from_normalized(
        item_type=ItemType.STOCK_NEWS,
        source_type=SourceType.STOCK,
        source_id=None,
        title="AAPL rallies on services growth",
        url="https://example.com/aapl-1",
        summary="Apple services beat estimates",
        published_at=datetime(2026, 8, 20, tzinfo=UTC),
        category="财报业绩",
        status=ItemStatus.CANDIDATE,
        score=1.0,
        metadata={"stock": {"tickers": [{"symbol": "AAPL", "name": "Apple", "exchange": "US"}], "themes": ["财报季"], "sentiment": "bullish"}},
    )
    md = render_monthly_brief(
        kind=BriefKind.STOCK,
        year_month="2026-08",
        items=[item],
        period_type="month",
    )
    assert "股票" in md or "市场资讯" in md
    assert "免责声明" in md
    assert "非投资建议" in md or "不构成投资建议" in md
