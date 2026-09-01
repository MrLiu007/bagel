"""Feishu command parse + notify + event challenge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, SourceType
from bagel.domain.models import Base
from bagel.main import create_app
from bagel.services import feishu_command, feishu_notify
from bagel.services.runtime_config import RuntimeConfig, save_runtime_config
from bagel.storage.database import get_db, get_engine, get_session_factory
from bagel.storage.repositories import ItemRepository

TZ = ZoneInfo("Asia/Shanghai")


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'feishu_cmd.db'}")
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
def client(db: Session, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    from bagel.settings import get_settings

    get_settings.cache_clear()
    save_runtime_config(RuntimeConfig(enable_feishu_cli=False).normalized())
    app = create_app()

    def _override():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_parse_date_range_keyword():
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    p = feishu_command.parse_command(
        "把8月20号到8月21号的体操方向新闻发我",
        now=now,
    )
    assert p.kind == "query"
    assert p.keyword == "体操"
    assert p.type_label == "新闻"
    assert p.start is not None and p.end is not None
    assert p.start.month == 8 and p.start.day == 20
    assert p.end.month == 8 and p.end.day == 21


def test_handle_query_hits_db(db: Session):
    repo = ItemRepository(db)
    pub = datetime(2026, 8, 20, 10, 0, tzinfo=TZ).astimezone(UTC)
    repo.upsert_from_normalized(
        item_type=ItemType.NEWS,
        source_type=SourceType.RSS,
        source_id=None,
        url="https://ex.com/gym1",
        title="国家体操队训练动态",
        published_at=pub,
        status=ItemStatus.CANDIDATE,
    )
    db.flush()
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    result = feishu_command.handle_command(
        db,
        "把8月20号到8月21号的体操方向新闻发我",
        now=now,
    )
    assert result.ok
    assert result.matched >= 1
    assert not result.crawled
    assert "体操" in result.text or "训练" in result.text


def test_feishu_events_url_verification(client: TestClient):
    resp = client.post(
        "/api/feishu/events",
        json={"type": "url_verification", "challenge": "abc123", "token": "t"},
    )
    assert resp.status_code == 200
    assert resp.json().get("challenge") == "abc123"


def test_feishu_command_api(client: TestClient, db: Session):
    resp = client.post("/api/feishu/command", json={"text": "帮助"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "飞书指令" in data["text"]


def test_format_collect_push():
    text = feishu_notify.format_collect_push(
        "collect_news",
        {"status": "success", "items_created": 3, "items_updated": 1, "items_found": 10},
    )
    assert "新闻采集" in text
    assert "新建：3" in text


def test_cli_page_shows_push_toggle(client: TestClient):
    resp = client.get("/settings?tab=cli")
    assert resp.status_code == 200
    assert "定时采集完成后异步推送飞书" in resp.text
    assert "/api/feishu/events" in resp.text
