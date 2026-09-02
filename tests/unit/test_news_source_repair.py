"""News source URL repair / migration."""

from __future__ import annotations

from bagel.domain.enums import Region, SourceType
from bagel.domain.models import Base, IntelSource
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.seed import repair_news_sources


def test_repair_news_sources(tmp_path) -> None:
    from sqlalchemy import select

    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'news.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    session.add(
        IntelSource(
            name="博客园精华",
            url="https://www.cnblogs.com/aggsite/rss",
            source_type=SourceType.RSS,
            region=Region.CN,
            enabled=True,
        )
    )
    session.add(
        IntelSource(
            name="LangChain Blog",
            url="https://blog.langchain.dev/rss/",
            source_type=SourceType.RSS,
            region=Region.GLOBAL,
            enabled=True,
        )
    )
    session.add(
        IntelSource(
            name="Meta AI",
            url="https://ai.meta.com/blog/rss/",
            source_type=SourceType.RSS,
            region=Region.GLOBAL,
            enabled=True,
        )
    )
    session.add(
        IntelSource(
            name="机器之心",
            url="https://www.jiqizhixin.com/rss",
            source_type=SourceType.RSS,
            region=Region.CN,
            enabled=True,
        )
    )
    session.commit()

    n = repair_news_sources(session)
    session.commit()
    assert n >= 4

    rows = list(session.scalars(select(IntelSource)).all())
    by_name = {r.name: r for r in rows}
    urls = {r.url for r in rows}

    assert "https://feed.cnblogs.com/blog/sitehome/rss" in urls
    assert "https://blog.langchain.dev/rss.xml" in urls
    assert "https://engineering.fb.com/feed/" in urls
    assert by_name["Meta Engineering"].url == "https://engineering.fb.com/feed/"
    assert by_name["机器之心"].enabled is False
    assert "https://www.ifanr.com/feed" in urls

    session.close()
    engine.dispose()
