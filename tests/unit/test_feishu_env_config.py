"""Feishu digest builder + env config UI helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bagel.domain.enums import BriefKind, ItemStatus, ItemType, SourceType
from bagel.domain.models import Base, IntelMonthlyBrief
from bagel.main import create_app
from bagel.services import env_config, feishu_digest
from bagel.services.monthly_brief import parse_year_week
from bagel.storage.database import get_db, get_engine, get_session_factory
from bagel.storage.repositories import ItemRepository


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'digest.db'}")
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


def test_schedule_label_without_reddit_text(client: TestClient):
    resp = client.get("/settings?tab=schedule")
    assert resp.status_code == 200
    assert "定时采集新闻" in resp.text
    assert "含 Reddit RSS" not in resp.text


def test_yesterday_digest_includes_types(db: Session):
    repo = ItemRepository(db)
    yesterday = datetime.now(UTC) - timedelta(days=1)
    specs = [
        (ItemType.NEWS, "https://ex.com/n1", "昨日新闻标题"),
        (ItemType.GITHUB_REPO, "https://github.com/a/b", "昨日项目"),
        (ItemType.PAPER, "https://arxiv.org/abs/1", "昨日论文"),
        (ItemType.STOCK_NEWS, "https://ex.com/s1", "昨日股票"),
        (ItemType.MEDIA_POST, "https://ex.com/m1", "昨日自媒体"),
        (ItemType.WECHAT_MSG, "https://ex.com/w1", "昨日微信"),
    ]
    for item_type, url, title in specs:
        repo.upsert_from_normalized(
            item_type=item_type,
            source_type=SourceType.RSS,
            source_id=None,
            title=title,
            url=url,
            summary="摘要",
            published_at=yesterday,
            status=ItemStatus.CANDIDATE,
            score=1.0,
        )
    payload = feishu_digest.build_yesterday_digest(db, per_type_limit=5)
    body = "\n".join(payload.chunks)
    assert "昨日资讯" in body
    for label in ("新闻", "GitHub项目", "论文", "股票", "自媒体", "微信"):
        assert label in body
    assert payload.section_counts.get("新闻", 0) >= 1


def test_week_briefs_digest_mentions_missing(db: Session):
    payload = feishu_digest.build_week_briefs_digest(db, which="this")
    body = "\n".join(payload.chunks)
    assert "周汇总" in body
    assert "尚未生成" in body or "新闻总结" in body


def test_week_briefs_digest_uses_existing_brief(db: Session):
    key = parse_year_week(None)
    db.add(
        IntelMonthlyBrief(
            year_month=key,
            kind=BriefKind.NEWS,
            title=f"{key} 新闻总结",
            markdown="# hello brief\n\n内容一段",
            item_count=1,
            template_version="test",
        )
    )
    db.flush()
    payload = feishu_digest.build_week_briefs_digest(db, which="this")
    body = "\n".join(payload.chunks)
    assert "hello brief" in body


def test_env_config_update_roundtrip(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("APP_PORT=8000\nENABLE_GITHUB=true\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from bagel.settings import get_settings

    get_settings.cache_clear()
    path = env_config.update_env_values(
        {"APP_PORT": "9001", "ENABLE_GITHUB": "false", "LOG_LEVEL": "DEBUG"},
        path=env_path,
    )
    text = path.read_text(encoding="utf-8")
    assert "APP_PORT=9001" in text
    assert "ENABLE_GITHUB=false" in text
    assert "LOG_LEVEL=DEBUG" in text
    groups = env_config.catalog_for_ui()
    assert any(g["group"] == "应用" for g in groups)
    get_settings.cache_clear()


def test_settings_config_and_cli_pages(client: TestClient):
    r = client.get("/settings?tab=config")
    assert r.status_code == 200
    assert "可视化编辑" in r.text or "APP_PORT" in r.text
    # Must not leak machine-absolute Windows/Unix paths (e.g. D:\coder\…\.env)
    assert "D:\\" not in r.text
    assert "D:/" not in r.text
    assert "/coder/liuzm" not in r.text
    assert ".env" in r.text
    r2 = client.get("/settings?tab=cli")
    assert r2.status_code == 200
    assert "推送昨日列表" in r2.text


def test_display_path_hides_absolute(monkeypatch, tmp_path):
    from bagel.pipeline import paths as path_util

    root = path_util.project_root()
    abs_env = root / ".env"
    assert path_util.display_path(abs_env) == ".env"
    abs_media = root / "third_party" / "MediaCrawler"
    assert path_util.display_path(abs_media) == "third_party/MediaCrawler"
    assert path_util.to_portable(str(abs_media)) == "third_party/MediaCrawler"
    # Outside project → truncated, no drive letter dump of full tree
    outside = Path("C:/Users/someone/.local/bin/lark-cli")
    shown = path_util.display_path(outside)
    assert "Users/someone" not in shown or shown.startswith("…/")
    assert not shown.lower().startswith("c:")


def test_env_update_rewrites_absolute_media_path(tmp_path, monkeypatch):
    from bagel.pipeline.paths import project_root

    env_path = tmp_path / ".env"
    env_path.write_text("MEDIA_CRAWLER_PATH=./x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    abs_media = str(project_root() / "third_party" / "MediaCrawler")
    path = env_config.update_env_values({"MEDIA_CRAWLER_PATH": abs_media}, path=env_path)
    text = path.read_text(encoding="utf-8")
    assert "third_party/MediaCrawler" in text
    assert "D:" not in text and abs_media not in text
