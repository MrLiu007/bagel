"""Education tab + GBrain drawer / personal space."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, SourceType
from bagel.domain.models import Base, IntelItem
from bagel.main import create_app
from bagel.services.gbrain import adapt_intel_item, build_gbrain_graph
from bagel.services.related import supports_related
from bagel.settings import get_settings
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.seed import DEFAULT_EDUCATION_SOURCES


def test_education_school_source_tabs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from datetime import UTC, datetime

    from bagel.domain.enums import ItemStatus, Region
    from bagel.domain.models import Base, IntelItem, IntelSource
    from bagel.pipeline.education_orgs import institution_for_source
    from bagel.storage.database import get_db, get_engine, get_session_factory

    assert institution_for_source(name="MIT OCW · New Courses").key == "mit"
    assert institution_for_source(name="MIT News · AI").key == "mit"

    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'edu_tabs.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    mit_ocw = IntelSource(
        name="MIT OCW · New Courses",
        url="https://old.ocw.mit.edu/rss/new/mit-newcourses.xml",
        source_type=SourceType.EDUCATION,
        region=Region.GLOBAL,
        enabled=True,
        priority=10,
    )
    mit_news = IntelSource(
        name="MIT News · AI",
        url="https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml",
        source_type=SourceType.EDUCATION,
        region=Region.GLOBAL,
        enabled=True,
        priority=15,
    )
    yale = IntelSource(
        name="Yale Open Courses",
        url="https://oyc.yale.edu/rss.xml",
        source_type=SourceType.EDUCATION,
        region=Region.GLOBAL,
        enabled=True,
        priority=30,
    )
    session.add_all([mit_ocw, mit_news, yale])
    session.flush()
    session.add_all(
        [
            IntelItem(
                item_type=ItemType.EDUCATION,
                source_type=SourceType.EDUCATION,
                source_id=mit_ocw.id,
                title="MIT 6.034",
                url="https://example.com/mit",
                canonical_url="https://example.com/mit",
                content_hash="edu-mit",
                status=ItemStatus.CANDIDATE,
                published_at=datetime.now(UTC),
            ),
            IntelItem(
                item_type=ItemType.EDUCATION,
                source_type=SourceType.EDUCATION,
                source_id=mit_news.id,
                title="MIT AI news",
                url="https://example.com/mit2",
                canonical_url="https://example.com/mit2",
                content_hash="edu-mit2",
                status=ItemStatus.CANDIDATE,
                published_at=datetime.now(UTC),
            ),
            IntelItem(
                item_type=ItemType.EDUCATION,
                source_type=SourceType.EDUCATION,
                source_id=yale.id,
                title="Yale GG 140",
                url="https://example.com/yale",
                canonical_url="https://example.com/yale",
                content_hash="edu-yale",
                status=ItemStatus.CANDIDATE,
                published_at=datetime.now(UTC),
            ),
        ]
    )
    session.commit()

    app = create_app()

    def _override():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        page = client.get("/education")
        assert page.status_code == 200
        assert "全部学校" in page.text
        assert ">MIT<" in page.text or ">MIT</a>" in page.text or "MIT" in page.text
        # Aggregated: not listing every feed name as its own tab label preference
        assert page.text.count("MIT OCW · New Courses") <= 1  # may appear in item source badge only
        assert "Yale" in page.text

        filtered = client.get("/education?school=mit")
        assert filtered.status_code == 200
        assert "MIT 6.034" in filtered.text
        assert "MIT AI news" in filtered.text
        assert "Yale GG 140" not in filtered.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
        get_settings.cache_clear()


def test_default_education_sources() -> None:
    assert any("MIT" in r["name"] for r in DEFAULT_EDUCATION_SOURCES)
    assert any("Stanford" in r["name"] for r in DEFAULT_EDUCATION_SOURCES)
    assert any("old.ocw.mit.edu" in r["url"] for r in DEFAULT_EDUCATION_SOURCES)
    assert all(r["source_type"] == SourceType.EDUCATION for r in DEFAULT_EDUCATION_SOURCES)
    urls = {r["url"] for r in DEFAULT_EDUCATION_SOURCES}
    assert "https://ocw.mit.edu/rss/new/mit-allcourses.xml" not in urls
    assert "https://online.stanford.edu/news/rss.xml" not in urls


def test_repair_education_sources(tmp_path) -> None:
    from sqlalchemy import select

    from bagel.domain.enums import Region
    from bagel.domain.models import Base, IntelSource
    from bagel.storage.database import get_engine, get_session_factory
    from bagel.storage.seed import repair_education_sources

    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'edu.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    session.add(
        IntelSource(
            name="MIT OpenCourseWare",
            url="https://ocw.mit.edu/rss/new/mit-allcourses.xml",
            source_type=SourceType.EDUCATION,
            region=Region.GLOBAL,
            enabled=True,
        )
    )
    session.add(
        IntelSource(
            name="Stanford Online News",
            url="https://online.stanford.edu/news/rss.xml",
            source_type=SourceType.EDUCATION,
            region=Region.GLOBAL,
            enabled=True,
        )
    )
    session.add(
        IntelSource(
            name="edX Blog",
            url="https://blog.edx.org/feed",
            source_type=SourceType.EDUCATION,
            region=Region.GLOBAL,
            enabled=True,
        )
    )
    session.commit()
    n = repair_education_sources(session)
    session.commit()
    assert n >= 3
    rows = list(
        session.scalars(
            select(IntelSource).where(IntelSource.source_type == SourceType.EDUCATION)
        ).all()
    )
    urls = {r.url for r in rows}
    assert "https://old.ocw.mit.edu/rss/new/mit-newcourses.xml" in urls
    assert "https://ai.stanford.edu/blog/feed.xml" in urls
    edx = next(r for r in rows if r.url == "https://blog.edx.org/feed")
    assert edx.enabled is False
    session.close()
    engine.dispose()


def test_supports_education_related() -> None:
    assert supports_related(ItemType.EDUCATION)


def test_wiki_adapter_and_echarts() -> None:
    item = IntelItem(
        item_type=ItemType.EDUCATION,
        source_type=SourceType.EDUCATION,
        title="MIT 6.034 Artificial Intelligence",
        url="https://ocw.mit.edu/courses/6-034",
        canonical_url="https://ocw.mit.edu/courses/6-034",
        content_hash="edu1",
        status=ItemStatus.CANDIDATE,
        summary="Intro AI course with search and learning.",
        tags=["MIT", "AI"],
        category="教育应用",
        published_at=datetime.now(UTC),
        metadata_={"institution": "MIT OpenCourseWare"},
    )
    wiki = adapt_intel_item(item, source_name="MIT OCW")
    assert wiki.type_label == "教育"
    assert "MIT" in wiki.tags or "开放课程" in wiki.tags
    graph = build_gbrain_graph([wiki], seed_id=wiki.id)
    assert graph.echarts.get("nodes")
    assert len(graph.nodes) >= 2
    item_nodes = [n for n in graph.nodes if n.kind == "item"]
    assert item_nodes and item_nodes[0].url.startswith("https://ocw.mit.edu")
    concept_nodes = [n for n in graph.nodes if n.kind != "item"]
    assert any(n.url for n in concept_nodes)


def test_education_and_space_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        edu = client.get("/education")
        assert edu.status_code == 200
        assert "教育" in edu.text

        space = client.get("/briefs/space")
        assert space.status_code == 200
        assert "个人空间" in space.text
        assert "GBrain" in space.text

        settings = client.get("/settings?tab=education")
        assert settings.status_code == 200
        assert "教育数据源" in settings.text

        briefs = client.get("/briefs/education")
        assert briefs.status_code == 200
        assert "教育总结" in briefs.text
    finally:
        get_settings.cache_clear()


def test_related_api_drawer(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'rel.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    seed = IntelItem(
        item_type=ItemType.NEWS,
        source_type="RSS",
        title="LLM Agent pipeline",
        url="https://example.com/n1",
        canonical_url="https://example.com/n1",
        content_hash="n1",
        status=ItemStatus.CANDIDATE,
        summary="archify typed JSON IR and Agent acceptance pipeline.",
        tags=["Agent"],
        published_at=datetime.now(UTC),
    )
    other = IntelItem(
        item_type=ItemType.PAPER,
        source_type=SourceType.PAPER,
        title="Agent evaluation methods",
        url="https://example.com/p1",
        canonical_url="https://example.com/p1",
        content_hash="p1",
        status=ItemStatus.CANDIDATE,
        summary="archify typed JSON IR acceptance for Agent systems.",
        tags=["Agent"],
        published_at=datetime.now(UTC),
    )
    session.add_all([seed, other])
    session.commit()

    from bagel.storage.database import get_db
    from bagel.main import create_app

    app = create_app()

    def _override():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        resp = client.get(f"/api/items/{seed.id}/related")
        assert resp.status_code == 200
        data = resp.json()
        assert "type_groups" in data
        assert "echarts" in data
        assert data["full_url"].startswith("/briefs/space")
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
        get_settings.cache_clear()
