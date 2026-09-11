"""Unit tests for Media → AV bridge."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, SourceType
from bagel.domain.models import Base, IntelItem
from bagel.services.av_bridge import (
    AvImportResult,
    import_media_post_to_av,
    is_importable_media_post,
    linked_av_id,
    media_post_platform,
)
from bagel.storage.database import get_engine, get_session_factory


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'av_bridge.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _media_item(**overrides) -> IntelItem:
    uid = uuid.uuid4()
    defaults = {
        "id": uid,
        "item_type": ItemType.MEDIA_POST,
        "source_type": SourceType.MEDIA,
        "title": "测试视频",
        "url": "https://www.bilibili.com/video/BV1test123",
        "canonical_url": "https://www.bilibili.com/video/BV1test123",
        "content_hash": str(uuid.uuid4()),
        "summary": "简介",
        "status": ItemStatus.CANDIDATE,
        "metadata_": {"platform": "bili", "external_id": "BV1test123"},
        "tags": ["bili", "AI"],
        "published_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return IntelItem(**defaults)


def test_media_post_platform_from_metadata() -> None:
    item = _media_item()
    assert media_post_platform(item) == "bili"


def test_is_importable_bilibili_video() -> None:
    assert is_importable_media_post(_media_item()) is True


def test_not_importable_weibo_text() -> None:
    item = _media_item(
        url="https://weibo.com/123",
        metadata_={"platform": "wb"},
        tags=["wb"],
    )
    assert is_importable_media_post(item) is False


def test_not_importable_when_already_linked() -> None:
    item = _media_item(metadata_={"platform": "bili", "av_item_id": str(uuid.uuid4())})
    assert is_importable_media_post(item) is False
    assert linked_av_id(item) is not None


def test_import_media_post_to_av_creates(db: Session) -> None:
    media = _media_item()
    db.add(media)
    db.flush()

    result = import_media_post_to_av(db, media.id)
    assert isinstance(result, AvImportResult)
    assert result.created is True
    assert result.av_item.item_type == ItemType.AV
    assert result.av_item.url == media.url
    assert result.av_item.metadata_["from_media_id"] == str(media.id)
    assert linked_av_id(result.media_item) == str(result.av_item.id)


def test_import_media_post_idempotent(db: Session) -> None:
    media = _media_item()
    db.add(media)
    db.flush()

    first = import_media_post_to_av(db, media.id)
    second = import_media_post_to_av(db, media.id)
    assert first.av_item.id == second.av_item.id
    assert second.created is False


def test_import_invalid_item_raises(db: Session) -> None:
    with pytest.raises(ValueError, match="不存在"):
        import_media_post_to_av(db, uuid.uuid4())


def test_bagel_entry_disables_media_download_by_default() -> None:
    from pathlib import Path

    text = (Path("third_party/patches/bagel_entry.py")).read_text(encoding="utf-8")
    assert "BAGEL_MC_GET_MEDIAS" in text
    assert "BAGEL_MC_GET_COMMENTS" in text
    assert "_env_bool" in text
    assert "_sanitize_venv_and_project_bom" in text or "_sanitize_opencv_bom" in text
    assert "execjs" in text or "BOM" in text


def test_can_enrich_and_rich_helpers() -> None:
    from bagel.services.av_bridge import can_enrich_media_transcript, item_has_rich_transcript

    bare = _media_item()
    assert can_enrich_media_transcript(bare) is True
    assert item_has_rich_transcript(bare) is False
    bare.content = "x" * 200
    assert item_has_rich_transcript(bare) is True
    assert can_enrich_media_transcript(bare) is False


def test_build_cmd_respects_comment_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from bagel.integrations import mediacrawler as mc
    from bagel.settings import Settings

    monkeypatch.setattr(mc, "_venv_python", lambda root: None)
    s = Settings(
        media_crawler_cmd="uv run bagel_entry.py",
        media_crawler_get_comments=True,
        media_crawler_get_sub_comments=False,
    )
    cmd = mc._build_cmd(
        root=Path("."),
        settings=s,
        platform="bili",
        keywords=["AI"],
    )
    assert "--get_comment" in cmd
    assert cmd[cmd.index("--get_comment") + 1] == "true"
    assert cmd[cmd.index("--get_sub_comment") + 1] == "false"
