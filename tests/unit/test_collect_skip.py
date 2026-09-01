"""Per-item collect failures should skip without aborting the job."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from bagel.domain.enums import SourceType
from bagel.domain.models import Base, IntelSource
from bagel.jobs.news import run_collect_news
from bagel.pipeline.textutil import clip
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.seed import seed_if_empty

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Mock</title>
  <item>
    <title>Open Source AI Agent Framework Release</title>
    <link>https://example.com/a</link>
    <description>agent framework</description>
    <pubDate>Mon, 30 Aug 2026 10:00:00 GMT</pubDate>
    <author>{"name": "x", "bio": "%s"}</author>
  </item>
  <item>
    <title>LLM RAG tutorial</title>
    <link>https://example.com/b</link>
    <description>rag llm</description>
    <pubDate>Mon, 30 Aug 2026 11:00:00 GMT</pubDate>
  </item>
</channel></rss>
""" % ("y" * 400)


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'skip.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def test_clip_respects_limit() -> None:
    assert clip("a" * 300, 255) is not None
    assert len(clip("a" * 300, 255) or "") == 255
    assert clip("  ", 10) is None


def test_collect_skips_bad_item_and_continues(db: Session) -> None:
    seed_if_empty(db)
    for s in db.query(IntelSource).all():
        s.enabled = False
    src = IntelSource(
        name="Mock Feed",
        url="https://example.com/feed.xml",
        source_type=SourceType.RSS,
        region="CN",
        enabled=True,
    )
    db.add(src)
    db.flush()

    from bagel.storage import repositories as repo_mod

    calls = {"n": 0}
    real_upsert = repo_mod.ItemRepository.upsert_from_normalized

    def flaky_upsert(self, *args, **kwargs):
        calls["n"] += 1
        title = kwargs.get("title") or ""
        if "Agent Framework" in title:
            raise ValueError("simulated bad row")
        return real_upsert(self, *args, **kwargs)

    def fake_fetch(url, **kwargs):
        return SAMPLE_RSS, 200, {}

    with (
        patch("bagel.collectors.rss.fetch_text", side_effect=fake_fetch),
        patch.object(repo_mod.ItemRepository, "upsert_from_normalized", flaky_upsert),
    ):
        result = run_collect_news(db)

    assert result["items_found"] == 2
    assert result["items_skipped"] == 1
    assert result["items_created"] >= 1
    assert result["status"] in {"SUCCESS", "PARTIAL"}

    from bagel.domain.models import IntelItem

    titles = {i.title for i in db.query(IntelItem).all()}
    assert "LLM RAG tutorial" in titles
