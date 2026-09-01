"""Phase 5: web review — favorite / ignore / top / deep-read / tags."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, SourceType
from bagel.domain.models import Base, IntelItem
from bagel.main import create_app
from bagel.services import review as review_svc
from bagel.settings import get_settings
from bagel.storage.database import get_db, get_engine, get_session_factory
from bagel.storage.repositories import ItemRepository


@pytest.fixture()
def db(tmp_path) -> Session:
    # File-backed SQLite avoids :memory: connection isolation under TestClient.
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'phase5.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db: Session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    app = create_app()

    def _override_db():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _seed_item(db: Session, **kwargs) -> IntelItem:
    repo = ItemRepository(db)
    item, _ = repo.upsert_from_normalized(
        item_type=kwargs.get("item_type", ItemType.NEWS),
        source_type=SourceType.RSS,
        source_id=None,
        title=kwargs.get("title", "Test AI Agent News"),
        url=kwargs.get("url", "https://example.com/a"),
        summary="summary",
        status=ItemStatus.CANDIDATE,
        score=1.0,
    )
    return item


def test_review_actions_service(db: Session) -> None:
    item = _seed_item(db)
    review_svc.favorite(db, item.id)
    assert item.is_favorite is True
    assert item.status == ItemStatus.CANDIDATE

    review_svc.mark_top(db, item.id)
    review_svc.mark_deep_read(db, item.id)
    assert item.is_top and item.is_deep_read

    review_svc.add_tags(db, item.id, ["agent", "rag", "agent"])
    assert item.tags == ["agent", "rag"]

    review_svc.ignore(db, item.id)
    assert item.status == ItemStatus.REJECTED
    assert item.is_favorite is False


def test_candidates_page_and_actions(client: TestClient, db: Session) -> None:
    item = _seed_item(db, title="Open Source RAG Framework", url="https://example.com/rag")

    resp = client.get("/news")
    assert resp.status_code == 200
    assert "Open Source RAG Framework" in resp.text
    assert "收藏" in resp.text
    assert "忽略" not in resp.text
    assert ">Top<" not in resp.text and "取消 Top" not in resp.text
    assert "Deep Read" not in resp.text
    assert "添加标签" not in resp.text

    resp = client.post(
        f"/items/{item.id}/action",
        data={"action": "favorite", "next": "/media?fragment=items"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/media"
    db.refresh(item)
    assert item.is_favorite is True
    assert item.status == ItemStatus.CANDIDATE

    # Favoriting must not remove the item from the candidate list.
    resp = client.get("/news")
    assert resp.status_code == 200
    assert "Open Source RAG Framework" in resp.text
    assert "取消收藏" in resp.text

    resp = client.post(
        f"/items/{item.id}/action",
        data={"action": "top", "next": "/favorites"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(item)
    assert item.is_top is True

    resp = client.get("/favorites")
    assert resp.status_code == 200
    assert "Open Source RAG Framework" in resp.text

    resp = client.post(
        f"/items/{item.id}/action",
        data={"action": "ignore", "next": "/ignored"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db.refresh(item)
    assert item.status == ItemStatus.REJECTED

    resp = client.get("/ignored")
    assert resp.status_code == 200
    assert "Open Source RAG Framework" in resp.text


def test_home_links_to_review(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "贝果" in resp.text
    assert "/news" in resp.text
    assert "今日候选" not in resp.text


def test_candidates_redirects_to_news(client: TestClient) -> None:
    resp = client.get("/candidates", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/news"


def test_settings_filter_tags(client: TestClient, db: Session) -> None:
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "过滤标签" in resp.text
    assert "系统状态" in resp.text

    resp = client.post(
        "/settings/tags",
        data={"keyword": "GraphRAG"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    from bagel.services import settings_svc

    tags = settings_svc.list_filter_tags(db)
    assert any(t.keyword == "GraphRAG" for t in tags)