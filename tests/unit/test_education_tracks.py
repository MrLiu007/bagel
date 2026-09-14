"""Unit tests for education tracks (公开课 / K12 / 考研)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from bagel.domain.enums import ItemStatus, ItemType, Region, SourceType
from bagel.domain.models import Base, IntelItem, IntelSource
from bagel.main import create_app
from bagel.pipeline.education_tracks import (
    EduTrack,
    build_education_url,
    facet_for_source,
    parse_education_url,
    track_for_source,
)
from bagel.settings import get_settings
from bagel.storage.database import get_db, get_engine, get_session_factory
from bagel.storage.seed import DEFAULT_EDUCATION_SOURCES, ensure_education_sources


def test_parse_and_build_education_url() -> None:
    plain = parse_education_url("https://oyc.yale.edu/rss.xml")
    assert plain.track == EduTrack.OPEN_COURSE
    assert plain.fetch_url == "https://oyc.yale.edu/rss.xml"

    stored = build_education_url("/gov/moe/newest_file", track="k12", facet="national")
    assert stored == "edu:k12:national:/gov/moe/newest_file"
    parsed = parse_education_url(stored)
    assert parsed.track == EduTrack.K12
    assert parsed.facet == "national"
    assert parsed.fetch_url == "/gov/moe/newest_file"

    ky = parse_education_url("edu:kaoyan:prospectus:https://yz.tsinghua.edu.cn/feed")
    assert ky.track == EduTrack.KAOYAN
    assert ky.facet == "prospectus"
    assert ky.fetch_url == "https://yz.tsinghua.edu.cn/feed"


def test_default_education_sources_include_tracks() -> None:
    tracks = {str(r.get("track") or "open_course") for r in DEFAULT_EDUCATION_SOURCES}
    assert "open_course" in tracks
    assert "k12" in tracks
    assert "kaoyan" in tracks
    assert any(r.get("facet") == "national" for r in DEFAULT_EDUCATION_SOURCES if r.get("track") == "k12")
    assert any(
        "/gov/moe/newest_file" == r["url"] for r in DEFAULT_EDUCATION_SOURCES if r.get("track") == "k12"
    )


def test_ensure_education_sources_adds_k12(tmp_path) -> None:
    from sqlalchemy import select

    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'edu_tracks.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    n = ensure_education_sources(session)
    session.commit()
    assert n >= 10
    rows = list(
        session.scalars(select(IntelSource).where(IntelSource.source_type == SourceType.EDUCATION)).all()
    )
    assert any(track_for_source(name=r.name, url=r.url) == EduTrack.K12 for r in rows)
    assert any("edu:k12:" in (r.url or "") for r in rows)
    # Idempotent
    assert ensure_education_sources(session) == 0
    session.close()
    engine.dispose()


def test_education_track_tabs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'edu_ui.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    ocw = IntelSource(
        name="MIT OCW · New Courses",
        url="https://old.ocw.mit.edu/rss/new/mit-newcourses.xml",
        source_type=SourceType.EDUCATION,
        region=Region.GLOBAL,
        enabled=True,
        priority=10,
    )
    moe = IntelSource(
        name="教育部 · 最新文件",
        url="edu:k12:national:/gov/moe/newest_file",
        source_type=SourceType.EDUCATION,
        region=Region.CN,
        enabled=True,
        priority=110,
    )
    session.add_all([ocw, moe])
    session.flush()
    session.add_all(
        [
            IntelItem(
                item_type=ItemType.EDUCATION,
                source_type=SourceType.EDUCATION,
                source_id=ocw.id,
                title="MIT 6.034",
                url="https://example.com/mit",
                canonical_url="https://example.com/mit",
                content_hash="edu-mit-t",
                status=ItemStatus.CANDIDATE,
                published_at=datetime.now(UTC),
                metadata_={"edu_track": "open_course"},
            ),
            IntelItem(
                item_type=ItemType.EDUCATION,
                source_type=SourceType.EDUCATION,
                source_id=moe.id,
                title="教育部发布义务教育新规",
                url="https://example.com/moe",
                canonical_url="https://example.com/moe",
                content_hash="edu-moe-t",
                status=ItemStatus.CANDIDATE,
                published_at=datetime.now(UTC),
                metadata_={"edu_track": "k12", "edu_facet": "national"},
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
        home = client.get("/education")
        assert home.status_code == 200
        assert "公开课" in home.text
        assert "K12" in home.text
        assert "考研" in home.text
        assert "MIT 6.034" in home.text
        assert "义务教育" not in home.text

        k12 = client.get("/education?track=k12")
        assert k12.status_code == 200
        assert "义务教育" in k12.text
        assert "MIT 6.034" not in k12.text
        assert "国家政策" in k12.text

        ky = client.get("/education?track=kaoyan")
        assert ky.status_code == 200
        assert "招生简章" in ky.text
        assert "MIT 6.034" not in ky.text

        settings = client.get("/settings?tab=education")
        assert settings.status_code == 200
        assert "公开课" in settings.text
        assert "K12" in settings.text
        assert "考研" in settings.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
        get_settings.cache_clear()


def test_infer_track_without_prefix() -> None:
    assert track_for_source(name="教育部 · 最新文件", url="/gov/moe/newest_file") == EduTrack.K12
    assert track_for_source(name="北京教委工会 · 通知", url="/gov/beijing/bjedu/gh") == EduTrack.K12
    assert (
        track_for_source(
            name="考研 · 国家政策（请改用研招网）",
            url="https://yz.chsi.com.cn/kyzx/yxzc/",
        )
        == EduTrack.KAOYAN
    )
    assert (
        track_for_source(name="清华研招 · 招生简章", url="https://yz.tsinghua.edu.cn/")
        == EduTrack.KAOYAN
    )
    assert track_for_source(name="Yale Open Courses", url="https://oyc.yale.edu/rss.xml") == (
        EduTrack.OPEN_COURSE
    )
    assert facet_for_source(name="教育部 · 政策解读", url="/gov/moe/policy_anal") == "reform"
    assert facet_for_source(name="清华研招 · 招生简章", url="https://yz.tsinghua.edu.cn/") == (
        "prospectus"
    )


def test_repair_reprefixes_misplaced_tracks(tmp_path) -> None:
    from sqlalchemy import select

    from bagel.storage.seed import repair_education_sources

    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'edu_fix.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    session.add_all(
        [
            IntelSource(
                name="教育部 · 最新文件",
                url="/gov/moe/newest_file",
                source_type=SourceType.EDUCATION,
                region=Region.CN,
                enabled=True,
            ),
            IntelSource(
                name="考研 · 国家政策（请改用研招网/目标校官网 RSS）",
                url="https://yz.chsi.com.cn/kyzx/yxzc/",
                source_type=SourceType.EDUCATION,
                region=Region.CN,
                enabled=False,
            ),
            IntelSource(
                name="北京教委工会 · 通知（城市参考）",
                url="/gov/beijing/bjedu/gh",
                source_type=SourceType.EDUCATION,
                region=Region.CN,
                enabled=False,
            ),
        ]
    )
    session.commit()
    n = repair_education_sources(session)
    session.commit()
    assert n >= 3
    rows = list(
        session.scalars(select(IntelSource).where(IntelSource.source_type == SourceType.EDUCATION)).all()
    )
    by_name = {r.name: r for r in rows}
    assert by_name["教育部 · 最新文件"].url.startswith("edu:k12:")
    assert track_for_source(name=by_name["教育部 · 最新文件"].name, url=by_name["教育部 · 最新文件"].url) == (
        EduTrack.K12
    )
    ky = by_name["考研 · 国家政策（请改用研招网/目标校官网 RSS）"]
    assert ky.url.startswith("edu:kaoyan:")
    assert track_for_source(name=ky.name, url=ky.url) == EduTrack.KAOYAN
    bj = by_name["北京教委工会 · 通知（城市参考）"]
    assert bj.url.startswith("edu:k12:")
    session.close()
    engine.dispose()


def test_education_settings_groups_by_inferred_track(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'edu_settings.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    session.add_all(
        [
            IntelSource(
                name="教育部 · 最新文件",
                url="/gov/moe/newest_file",
                source_type=SourceType.EDUCATION,
                region=Region.CN,
                enabled=True,
            ),
            IntelSource(
                name="考研 · 国家政策（请改用研招网）",
                url="https://yz.chsi.com.cn/kyzx/yxzc/",
                source_type=SourceType.EDUCATION,
                region=Region.CN,
                enabled=False,
            ),
            IntelSource(
                name="Yale Open Courses",
                url="https://oyc.yale.edu/rss.xml",
                source_type=SourceType.EDUCATION,
                region=Region.GLOBAL,
                enabled=True,
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
        page = client.get("/settings?tab=education")
        assert page.status_code == 200
        # Under K12 section heading, 教育部 should appear; not only under 公开课.
        text = page.text
        k12_pos = text.find(">K12<")
        if k12_pos < 0:
            k12_pos = text.find("K12")
        ky_pos = text.find("考研")
        moe_pos = text.find("教育部 · 最新文件")
        assert k12_pos > 0 and moe_pos > k12_pos
        # 公开课 school filter must not list 教育部
        edu = client.get("/education?track=open_course")
        assert edu.status_code == 200
        assert "教育部" not in edu.text or "Yale" in edu.text
        # Harder: school tab strip should not contain 教育部 as a tab label near 学校
        assert ">教育部<" not in edu.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
        get_settings.cache_clear()

