"""Title keyword (`q`) filter on list_by_status / list_candidates."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, SourceType
from bagel.domain.models import Base, IntelItem
from bagel.services import review as review_svc
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.repositories import ItemRepository, normalize_title_q


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'title_q.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _add(
    db: Session,
    *,
    title: str,
    llm_title_zh: str | None = None,
    item_type: str = ItemType.NEWS,
    category: str | None = None,
) -> IntelItem:
    row = IntelItem(
        item_type=item_type,
        source_type=SourceType.RSS,
        title=title,
        llm_title_zh=llm_title_zh,
        url=f"https://example.com/{uuid4()}",
        canonical_url=f"https://example.com/{uuid4()}",
        content_hash=str(uuid4()),
        status=ItemStatus.CANDIDATE,
        category=category,
        published_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


def test_normalize_title_q() -> None:
    assert normalize_title_q(None) is None
    assert normalize_title_q("  ") is None
    assert normalize_title_q("  Agent  ") == "Agent"
    assert len(normalize_title_q("x" * 200) or "") == 128


def test_list_by_status_title_and_zh(db: Session) -> None:
    _add(db, title="Open Agent Framework")
    _add(db, title="Other paper", llm_title_zh="智能体综述")
    _add(db, title="Unrelated news")
    repo = ItemRepository(db)

    by_en = repo.list_by_status(ItemStatus.CANDIDATE, item_type=ItemType.NEWS, q="Agent")
    assert len(by_en) == 1
    assert "Agent" in by_en[0].title

    by_zh = repo.list_by_status(ItemStatus.CANDIDATE, item_type=ItemType.NEWS, q="智能体")
    assert len(by_zh) == 1
    assert by_zh[0].llm_title_zh == "智能体综述"

    assert repo.count_by_status(ItemStatus.CANDIDATE, item_type=ItemType.NEWS, q="Agent") == 1


def test_title_q_with_category_and_type(db: Session) -> None:
    _add(db, title="LLM Agent News", category="AI", item_type=ItemType.NEWS)
    _add(db, title="LLM Agent Paper", category="AI", item_type=ItemType.PAPER)
    _add(db, title="LLM Agent News", category="Robotics", item_type=ItemType.NEWS)
    repo = ItemRepository(db)

    rows = repo.list_by_status(
        ItemStatus.CANDIDATE,
        item_type=ItemType.NEWS,
        category="AI",
        q="Agent",
    )
    assert len(rows) == 1
    assert rows[0].category == "AI"
    assert rows[0].item_type == ItemType.NEWS

    cats = repo.list_categories(
        ItemStatus.CANDIDATE, item_type=ItemType.NEWS, q="Agent"
    )
    assert set(cats) == {"AI", "Robotics"}


def test_list_candidates_passes_q(db: Session) -> None:
    _add(db, title="Bagel release notes")
    _add(db, title="Other")
    page = review_svc.list_candidates(db, item_type=ItemType.NEWS, q="bagel", page=1)
    assert page.total == 1
    assert "Bagel" in page.items[0].title


def test_news_page_preserves_q(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from bagel.main import create_app
    from bagel.settings import get_settings
    from bagel.storage.database import get_db
    from bagel.storage.seed import seed_if_empty

    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    seed_if_empty(db)
    _add(db, title="UniqueKeywordXYZ headline")
    _add(db, title="Something else")
    db.commit()

    app = create_app()

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = TestClient(app)
    resp = client.get("/news", params={"q": "UniqueKeywordXYZ"})
    assert resp.status_code == 200
    body = resp.text
    assert "UniqueKeywordXYZ" in body
    assert "Something else" not in body
    assert 'name="q"' in body
    assert "page=2" not in body or "q=UniqueKeywordXYZ" in body or "q=UniqueKeyword" in body
