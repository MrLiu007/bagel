"""AV subtitle / transcript extraction (CC → soft-sub → ASR)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, SourceType
from bagel.domain.models import Base, IntelItem
from bagel.jobs.av import heal_av_local_download, run_extract_av_subtitles
from bagel.settings import Settings
from bagel.storage.database import get_engine, get_session_factory


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'av_subs.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _av_item(**overrides) -> IntelItem:
    uid = uuid.uuid4()
    defaults = {
        "id": uid,
        "item_type": ItemType.AV,
        "source_type": SourceType.AV,
        "title": "抖音短视频",
        "url": "https://www.douyin.com/video/7683125314574126363",
        "canonical_url": "https://www.douyin.com/video/7683125314574126363",
        "content_hash": str(uuid.uuid4()),
        "summary": "",
        "content": "",
        "status": ItemStatus.CANDIDATE,
        "metadata_": {"platform": "douyin"},
        "tags": ["douyin"],
        "published_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return IntelItem(**defaults)


def _patch_no_remote_subs(monkeypatch) -> None:
    monkeypatch.setattr(
        "bagel.integrations.ytdlp.extract_subtitles_only",
        lambda *a, **k: {
            "status": "failed",
            "error": "无字幕",
            "reason": "no_subtitle_tracks",
        },
    )


def test_heal_av_local_download_marks_done(db: Session, tmp_path: Path, monkeypatch) -> None:
    settings = Settings(data_dir=str(tmp_path / "data"))
    item = _av_item(
        metadata_={
            "platform": "douyin",
            "download": {"status": "failed", "error": "下载完成但未找到媒体文件"},
        }
    )
    db.add(item)
    db.flush()
    media_dir = Path(settings.data_dir) / "av" / "files" / str(item.id)
    media_dir.mkdir(parents=True)
    (media_dir / f"{item.id}.mp4").write_bytes(b"fake-mp4")

    monkeypatch.setattr("bagel.settings.get_settings", lambda: settings)
    assert heal_av_local_download(item, settings=settings) is True
    dl = item.metadata_["download"]
    assert dl["status"] == "done"
    assert dl["error"] is None
    assert str(item.id) in dl["local_path"]


def test_extract_uses_asr_not_author_desc(db: Session, tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        av_asr_enabled=True,
        av_fallback_author_desc=False,
    )
    item = _av_item(title="短标题", summary="这是作者提供的长简介文案内容足够十二字")
    db.add(item)
    db.flush()
    media_dir = Path(settings.data_dir) / "av" / "files" / str(item.id)
    media_dir.mkdir(parents=True)
    mp4 = media_dir / f"{item.id}.mp4"
    mp4.write_bytes(b"fake-mp4-bytes")

    _patch_no_remote_subs(monkeypatch)
    monkeypatch.setattr(
        "bagel.integrations.av_transcript.extract_soft_subtitles",
        lambda *a, **k: {"status": "failed", "reason": "no_soft_subs"},
    )
    monkeypatch.setattr(
        "bagel.integrations.av_transcript.probe_media_streams",
        lambda *a, **k: {"ok": True, "has_soft_subs": False, "streams": []},
    )
    monkeypatch.setattr(
        "bagel.integrations.av_transcript.transcribe_local_media",
        lambda *a, **k: {
            "status": "done",
            "text": "我们来说一下这一周的AI大事件",
            "backend": "faster_whisper",
            "reason": "asr_local",
        },
    )

    result = run_extract_av_subtitles(db, item_id=item.id, settings=settings)
    assert result["status"] == "SUCCESS"
    assert item.metadata_["subtitle"]["source"] == "asr"
    assert "AI大事件" in (item.content or "")
    assert "作者提供" not in (item.content or "")


def test_extract_does_not_use_desc_when_fallback_off(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        av_asr_enabled=False,
        av_fallback_author_desc=False,
    )
    item = _av_item(summary="这是作者提供的长简介文案内容足够十二字")
    db.add(item)
    db.flush()
    media_dir = Path(settings.data_dir) / "av" / "files" / str(item.id)
    media_dir.mkdir(parents=True)
    (media_dir / f"{item.id}.mp4").write_bytes(b"x")

    _patch_no_remote_subs(monkeypatch)
    monkeypatch.setattr(
        "bagel.integrations.av_transcript.extract_soft_subtitles",
        lambda *a, **k: {"status": "failed", "reason": "no_soft_subs"},
    )
    monkeypatch.setattr(
        "bagel.integrations.av_transcript.probe_media_streams",
        lambda *a, **k: {"ok": True, "has_soft_subs": False},
    )

    result = run_extract_av_subtitles(db, item_id=item.id, settings=settings)
    assert result["status"] == "FAILED"
    assert "烧录" in (result.get("error") or "")


def test_extract_optional_author_desc_when_enabled(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        av_asr_enabled=False,
        av_fallback_author_desc=True,
    )
    item = _av_item()
    db.add(item)
    db.flush()

    _patch_no_remote_subs(monkeypatch)
    monkeypatch.setattr(
        "bagel.integrations.ytdlp.fetch_entry_description",
        lambda *a, **k: {
            "status": "done",
            "description": "这是一段足够长的抖音视频文案描述内容",
            "title": "短标题",
        },
    )
    monkeypatch.setattr(
        "bagel.integrations.ytdlp.find_local_av_media",
        lambda *a, **k: None,
    )

    result = run_extract_av_subtitles(db, item_id=item.id, settings=settings)
    assert result["status"] == "SUCCESS"
    assert item.metadata_["subtitle"]["source"] == "description"
    assert "非字幕" in (item.metadata_["subtitle"].get("note") or "")


def test_srt_to_plain_helper() -> None:
    from bagel.integrations.av_transcript import _srt_to_plain

    srt = "1\n00:00:00,000 --> 00:00:01,000\n你好世界\n\n2\n00:00:01,000 --> 00:00:02,000\n第二行\n"
    assert "你好世界" in _srt_to_plain(srt)
    assert "第二行" in _srt_to_plain(srt)
