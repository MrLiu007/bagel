"""Tests for education preset resolve / quick-add."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bagel.domain.enums import Region, SourceType
from bagel.domain.models import Base, IntelSource
from bagel.main import create_app
from bagel.pipeline.education_presets import resolve_presets
from bagel.pipeline.education_tracks import EduTrack, track_for_source
from bagel.services import settings_svc
from bagel.settings import get_settings
from bagel.storage.database import get_db, get_engine, get_session_factory


def test_resolve_k12_and_kaoyan_presets() -> None:
    matched, unmatched = resolve_presets("北京,广东", kind="k12_region")
    assert unmatched == []
    assert any(p.fetch_url.startswith("/gov/beijing/") for p in matched)
    assert any("guangdong" in p.fetch_url for p in matched)

    schools, bad = resolve_presets("北大、浙大、研招网", kind="kaoyan_school")
    assert bad == []
    assert any(p.key == "pku" for p in schools)
    assert any(p.key == "zju" for p in schools)
    assert any(p.key.startswith("chsi") for p in schools)

    _, miss = resolve_presets("火星教育厅", kind="k12_region")
    assert miss == ["火星教育厅"]


def test_add_education_presets_idempotent(tmp_path) -> None:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'edu_preset.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    r1 = settings_svc.add_education_presets(session, query="北大", kind="kaoyan_school")
    assert r1["added"] == 1
    r2 = settings_svc.add_education_presets(session, query="北京大学", kind="kaoyan_school")
    assert r2["added"] == 1
    rows = list(
        session.scalars(select(IntelSource).where(IntelSource.source_type == SourceType.EDUCATION)).all()
    )
    assert len(rows) == 1
    assert track_for_source(name=rows[0].name, url=rows[0].url) == EduTrack.KAOYAN
    assert "watch:kaoyan:北京大学" in (rows[0].url or "")
    session.close()
    engine.dispose()


def test_add_any_city_or_school_as_watch(tmp_path) -> None:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'edu_watch.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    k12 = settings_svc.add_education_presets(session, query="成都", kind="k12_region")
    assert k12["added"] == 1
    ky = settings_svc.add_education_presets(session, query="四川大学", kind="kaoyan_school")
    assert ky["added"] == 1
    rows = list(
        session.scalars(select(IntelSource).where(IntelSource.source_type == SourceType.EDUCATION)).all()
    )
    assert any("watch:k12:成都" in (r.url or "") for r in rows)
    assert any("watch:kaoyan:四川大学" in (r.url or "") for r in rows)
    session.close()
    engine.dispose()


def test_preset_settings_ui(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'edu_preset_ui.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
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
        assert "快捷添加 · K12 省市" in page.text
        assert "快捷添加 · 考研院校" in page.text
        assert "公开课" in page.text
        assert "可自动生成的省市" not in page.text
        assert "手动添加（高级）" not in page.text
        assert "教育源分三轨" not in page.text
        assert "自定义" in page.text

        resp = client.post(
            "/settings/education/preset",
            data={"kind": "k12_region", "query": "广东"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "tab=education" in resp.headers.get("location", "")
        rows = list(
            session.scalars(
                select(IntelSource).where(IntelSource.source_type == SourceType.EDUCATION)
            ).all()
        )
        assert any("guangdong" in (r.url or "") for r in rows)
        assert all(r.region == Region.CN for r in rows if "guangdong" in (r.url or ""))

        # Unmatched city → watch subscription (success, not err)
        miss = client.post(
            "/settings/education/preset",
            data={"kind": "k12_region", "query": "成都"},
            follow_redirects=False,
        )
        assert miss.status_code == 303
        loc = miss.headers.get("location", "")
        assert "err=1" not in loc
        rows_watch = list(
            session.scalars(
                select(IntelSource).where(IntelSource.source_type == SourceType.EDUCATION)
            ).all()
        )
        assert any("watch:k12:成都" in (r.url or "") for r in rows_watch)

        # Custom path for school
        custom = client.post(
            "/settings/education/preset",
            data={
                "kind": "kaoyan_school",
                "query": "某校",
                "custom_url": "/scu/jwc/notice",
            },
            follow_redirects=False,
        )
        assert custom.status_code == 303
        assert "err=1" not in custom.headers.get("location", "")
        rows2 = list(
            session.scalars(
                select(IntelSource).where(IntelSource.source_type == SourceType.EDUCATION)
            ).all()
        )
        assert any("/scu/jwc/notice" in (r.url or "") for r in rows2)
        assert any("某校" in (r.name or "") for r in rows2)
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
        get_settings.cache_clear()
