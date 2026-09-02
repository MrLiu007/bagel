"""Briefs dashboard, custom prompts, keyword growth."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bagel.domain.enums import BriefKind, ItemType
from bagel.domain.models import Base, IntelSearchEvent
from bagel.jobs.keyword_growth import run_expand_keywords_from_search
from bagel.main import create_app
from bagel.services import brief_prompts, search_analytics
from bagel.services.gbrain import build_knowledge_graph
from bagel.services.monthly_brief import write_monthly_brief
from bagel.settings import get_settings
from bagel.storage.database import get_engine, get_session_factory


@pytest.fixture()
def db(tmp_path):
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'dash.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def test_log_search_and_rankings(db: Session) -> None:
    search_analytics.log_search(
        db,
        query="LLM Agent",
        item_types=(ItemType.NEWS,),
        hit_count=3,
        channel="dashboard",
    )
    search_analytics.log_search(
        db,
        query="LLM Agent",
        item_types=(ItemType.NEWS,),
        hit_count=1,
        channel="feishu",
    )
    db.flush()
    assert search_analytics.search_count(db) == 2
    ranks = search_analytics.keyword_rankings(db)
    assert ranks[0]["keyword"] == "LLM Agent"
    assert ranks[0]["searches"] == 2


def test_gbrain_builds_links(db: Session) -> None:
    from bagel.domain.enums import ItemStatus
    from bagel.domain.models import IntelItem
    from datetime import UTC, datetime

    for i in range(5):
        db.add(
            IntelItem(
                item_type=ItemType.NEWS,
                source_type="RSS",
                title=f"LLM Agent release {i}",
                url=f"https://example.com/a{i}",
                canonical_url=f"https://example.com/a{i}",
                content_hash=f"a{i}",
                status=ItemStatus.CANDIDATE,
                category="大模型/LLM",
                tags=["LLM", "Agent"],
                published_at=datetime.now(UTC),
            )
        )
    db.flush()
    graph = build_knowledge_graph(db, limit=20)
    assert graph.nodes
    assert graph.top_links or graph.edges
    item_nodes = [n for n in graph.nodes if n.kind == "item"]
    assert len(item_nodes) >= 3
    assert all(n.url for n in item_nodes)
    clickable = [n for n in graph.nodes if n.url]
    assert len(clickable) >= len(item_nodes)
    assert graph.echarts.get("stats", {}).get("items", 0) >= 3


def test_briefs_space_hides_related_drawer(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    from bagel.storage.database import get_db

    app = create_app()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        news = client.get("/news")
        assert news.status_code == 200
        assert 'id="related-drawer"' in news.text
        assert 'hidden aria-hidden="true"' in news.text or 'hidden aria-hidden=\'true\'' in news.text
        # Closed drawer must not show loading placeholder in page flow
        assert "加载中…" not in news.text
        assert 'class="related-drawer open"' not in news.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_keyword_growth_from_search(db: Session) -> None:
    for _ in range(2):
        search_analytics.log_search(
            db,
            query="GraphRAG",
            item_types=(ItemType.NEWS,),
            hit_count=1,
            channel="web",
        )
    db.flush()
    result = run_expand_keywords_from_search(db)
    assert result["include_added"] >= 1


def test_brief_custom_prompt_stored(db: Session) -> None:
    bundle = write_monthly_brief(
        db,
        kind=BriefKind.NEWS,
        year_month="2099-01",
        custom_prompt="重点讲 LLM 推理成本",
        save_prompt_default=True,
    )
    assert "LLM" in bundle.brief.metadata_.get("user_prompt", "")
    assert bundle.brief.metadata_.get("prompt_used")
    assert brief_prompts.load_default(BriefKind.NEWS) == "重点讲 LLM 推理成本"


def test_briefs_dashboard_route(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    from bagel.storage.database import get_db

    app = create_app()

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        redirect = client.get("/briefs/dashboard", follow_redirects=False)
        assert redirect.status_code in {301, 302, 307, 308}
        resp = client.get("/briefs/space")
        assert resp.status_code == 200
        assert "个人空间" in resp.text
        assert "GBrain" in resp.text
        resp2 = client.get("/briefs/space?q=Agent")
        assert resp2.status_code == 200
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
