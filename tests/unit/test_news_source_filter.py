"""News source filter + overseas collect skip behaviour."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bagel.collectors.rss import CollectResult
from bagel.domain.contracts import NormalizedItem
from bagel.domain.enums import ItemStatus, ItemType, JobStatus, Region, SourceType
from bagel.domain.models import Base, IntelItem, IntelSource
from bagel.jobs.news import run_collect_news
from bagel.main import create_app
from bagel.settings import get_settings
from bagel.storage.database import get_db, get_engine, get_session_factory
from bagel.storage.repositories import ItemRepository
from bagel.storage.seed import DEFAULT_X_SOURCES, ensure_x_sources, seed_if_empty


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'news_src.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def test_ensure_x_sources_idempotent(db: Session) -> None:
    assert len(DEFAULT_X_SOURCES) >= 3
    n1 = ensure_x_sources(db)
    assert n1 == len(DEFAULT_X_SOURCES)
    n2 = ensure_x_sources(db)
    assert n2 == 0


def test_list_by_status_filters_source_id(db: Session) -> None:
    s1 = IntelSource(name="A", url="https://a.example/rss", source_type=SourceType.RSS, enabled=True)
    s2 = IntelSource(name="B", url="https://b.example/rss", source_type=SourceType.RSS, enabled=True)
    db.add_all([s1, s2])
    db.flush()
    for src, title in ((s1, "News A"), (s2, "News B")):
        db.add(
            IntelItem(
                item_type=ItemType.NEWS,
                source_type=SourceType.RSS,
                source_id=src.id,
                title=title,
                url=f"https://example.com/{src.id}",
                canonical_url=f"https://example.com/{src.id}",
                content_hash=str(uuid4()),
                status=ItemStatus.CANDIDATE,
                published_at=datetime.now(UTC),
            )
        )
    db.flush()
    repo = ItemRepository(db)
    rows = repo.list_by_status(ItemStatus.CANDIDATE, item_type=ItemType.NEWS, source_id=s1.id)
    assert len(rows) == 1
    assert rows[0].title == "News A"
    assert repo.count_by_status(ItemStatus.CANDIDATE, item_type=ItemType.NEWS, source_id=s1.id) == 1


def test_news_page_source_filter(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    seed_if_empty(db)
    src = IntelSource(
        name="FilterFeed",
        url="https://filter.example/rss",
        source_type=SourceType.RSS,
        region=Region.CN,
        enabled=True,
    )
    db.add(src)
    db.flush()
    db.add(
        IntelItem(
            item_type=ItemType.NEWS,
            source_type=SourceType.RSS,
            source_id=src.id,
            title="Visible From Source",
            url="https://example.com/vis",
            canonical_url="https://example.com/vis",
            content_hash=str(uuid4()),
            status=ItemStatus.CANDIDATE,
            published_at=datetime.now(UTC),
        )
    )
    db.flush()

    app = create_app()

    def _override():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        all_page = client.get("/news")
        assert all_page.status_code == 200
        assert "来源" in all_page.text
        assert "news-source-filter" in all_page.text
        filtered = client.get(f"/news?source_id={src.id}")
        assert filtered.status_code == 200
        assert "Visible From Source" in filtered.text
        assert "FilterFeed" in filtered.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_overseas_failure_does_not_abort_cn(db: Session) -> None:
    for s in db.query(IntelSource).all():
        s.enabled = False
    cn = IntelSource(
        name="CN Mock",
        url="https://cn.example/rss",
        source_type=SourceType.RSS,
        region=Region.CN,
        enabled=True,
        priority=1,
    )
    gl = IntelSource(
        name="GLOBAL Mock",
        url="https://global.example/rss",
        source_type=SourceType.RSS,
        region=Region.GLOBAL,
        network_requirement="PROXY_PREFERRED",
        enabled=True,
        priority=2,
    )
    db.add_all([cn, gl])
    db.flush()

    def fake_collect(self, source: IntelSource) -> CollectResult:
        if source.region == Region.GLOBAL:
            return CollectResult(error_code="NETWORK_UNREACHABLE", error_message="blocked")
        item = NormalizedItem(
            item_type=ItemType.NEWS,
            source_type=SourceType.RSS,
            source_id=source.id,
            title="Domestic AI News Item",
            url="https://cn.example/a",
            canonical_url="https://cn.example/a",
            summary="llm agent",
            published_at=datetime.now(UTC),
            raw_payload={"t": 1},
        )
        return CollectResult(items=[item], http_status=200)

    with patch("bagel.jobs.news.RssCollector.collect_source", fake_collect):
        result = run_collect_news(db)

    assert result["items_created"] >= 1
    assert result["global_failed"] >= 1
    assert result["status"] in {JobStatus.SUCCESS, JobStatus.PARTIAL}
    assert any("[GLOBAL]" in e for e in result["errors"])
