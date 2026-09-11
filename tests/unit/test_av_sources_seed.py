"""AV default source seed + repair for wrong Bilibili mids."""

from __future__ import annotations

from sqlalchemy import select

from bagel.domain.enums import Region, SourceType
from bagel.domain.models import Base, IntelSource
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.seed import (
    DEFAULT_AV_SOURCES,
    ensure_av_sources,
    repair_av_sources,
)


def test_default_av_sources_are_lean() -> None:
    assert len(DEFAULT_AV_SOURCES) == 6
    by_name = {r["name"]: r for r in DEFAULT_AV_SOURCES}
    assert "验通·直链样片（免 Cookie）" in by_name
    assert "验通·Internet Archive" in by_name
    assert by_name["跟李沐学 AI"]["url"] == "av:bilibili:mid:1567748478"
    assert by_name["机器之心官方"]["url"] == "av:bilibili:mid:73414544"
    assert by_name["爱可可-爱生活"]["url"] == "av:bilibili:mid:23852932"
    assert by_name["量子位Daily"]["url"] == "av:bilibili:mid:3546619041548912"
    urls = {r["url"] for r in DEFAULT_AV_SOURCES}
    assert "av:bilibili:mid:15634833" not in urls
    assert "清华大学" not in by_name
    assert any("wikimedia.org" in u for u in urls)
    assert any("archive.org" in u for u in urls)

def test_repair_av_sources_migrates_and_purges(tmp_path) -> None:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'av_seed.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    session.add(
        IntelSource(
            name="跟李沐学 AI",
            url="av:bilibili:mid:15634833",
            source_type=SourceType.AV,
            region=Region.CN,
            enabled=True,
            last_error_code="YTDLP_ERROR",
        )
    )
    session.add(
        IntelSource(
            name="机器之心 SOTA",
            url="av:bilibili:mid:320334464",
            source_type=SourceType.AV,
            region=Region.CN,
            enabled=True,
        )
    )
    session.add(
        IntelSource(
            name="清华大学",
            url="av:bilibili:mid:515087961",
            source_type=SourceType.AV,
            region=Region.CN,
            enabled=True,
        )
    )
    session.add(
        IntelSource(
            name="我的抖音博主",
            url="https://www.douyin.com/user/MS4wLjABAAAA_test",
            source_type=SourceType.AV,
            region=Region.CN,
            enabled=True,
        )
    )
    session.flush()

    n = repair_av_sources(session)
    assert n >= 3
    session.flush()
    ensure_av_sources(session)
    session.flush()

    rows = list(
        session.scalars(select(IntelSource).where(IntelSource.source_type == SourceType.AV))
    )
    urls = {(r.url or "") for r in rows}
    assert "av:bilibili:mid:1567748478" in urls
    assert "av:bilibili:mid:73414544" in urls
    assert "av:bilibili:mid:515087961" not in urls
    assert "av:bilibili:mid:15634833" not in urls
    assert "https://www.douyin.com/user/MS4wLjABAAAA_test" in urls
    limu = next(r for r in rows if r.url == "av:bilibili:mid:1567748478")
    assert limu.enabled is True
    assert limu.last_error_code is None
    session.commit()
    session.close()
    engine.dispose()
