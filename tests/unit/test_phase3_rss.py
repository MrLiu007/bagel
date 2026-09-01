"""Phase 3: filter, dedup, normalize, RSS collect (mocked HTTP)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from bagel.collectors.rss import RssCollector
from bagel.domain.enums import ItemStatus, KeywordRuleType, SourceType
from bagel.domain.models import Base, IntelKeywordRule, IntelSource
from bagel.jobs.news import run_collect_news
from bagel.pipeline.dedup import is_duplicate
from bagel.pipeline.filter import apply_keyword_rules
from bagel.pipeline.normalize import from_rss_entry
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.seed import DEFAULT_SOURCES, seed_if_empty


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Open Source AI Agent Framework Release</title>
      <link>https://example.com/agent-1</link>
      <description>A new RAG-friendly agent toolkit.</description>
      <pubDate>Mon, 30 Aug 2026 10:00:00 GMT</pubDate>
      <guid>https://example.com/agent-1</guid>
    </item>
    <item>
      <title>付费课程培训招生火热</title>
      <link>https://example.com/ad-1</link>
      <description>荐股与娱乐八卦</description>
      <pubDate>Mon, 30 Aug 2026 09:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Unrelated cooking tips</title>
      <link>https://example.com/food</link>
      <description>Pasta recipes</description>
      <pubDate>Sun, 29 Aug 2026 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.fixture()
def db() -> Session:
    engine = get_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def test_at_least_20_default_sources() -> None:
    assert len(DEFAULT_SOURCES) >= 20
    regions = {s["region"] for s in DEFAULT_SOURCES}
    assert "CN" in regions and "GLOBAL" in regions


def test_seed_idempotent(db: Session) -> None:
    a = seed_if_empty(db)
    b = seed_if_empty(db)
    assert a["sources"] >= 20
    assert b["sources"] == 0
    assert a["keywords"] > 0
    assert a["github_queries"] >= 8


def test_exclude_and_include_filter(db: Session) -> None:
    rules = [
        IntelKeywordRule(keyword="培训招生", rule_type=KeywordRuleType.EXCLUDE),
        IntelKeywordRule(keyword="AI Agent", rule_type=KeywordRuleType.INCLUDE, weight=2.0),
        IntelKeywordRule(keyword="RAG", rule_type=KeywordRuleType.BOOST, weight=1.5),
    ]
    rejected = apply_keyword_rules("付费课程培训招生", None, rules)
    assert rejected.accepted is False
    assert rejected.status == ItemStatus.REJECTED

    accepted = apply_keyword_rules("Open Source AI Agent with RAG", "notes", rules)
    assert accepted.accepted is True
    assert accepted.score >= 3.5

    no_include = apply_keyword_rules("Unrelated cooking", None, rules)
    assert no_include.accepted is False


def test_dedup_helpers() -> None:
    urls = {"https://example.com/a"}
    hashes = set()
    assert is_duplicate(
        url="https://example.com/a?x=1",
        title="Hello",
        existing_canonical_urls=urls,
        existing_hashes=hashes,
    )


def test_normalize_rss_entry() -> None:
    item = from_rss_entry(
        {"title": "T", "link": "https://Ex.COM/Path/", "summary": "S", "id": "1"},
        source_id=None,
        source_type=SourceType.RSS,
    )
    assert item is not None
    assert item.canonical_url == "https://ex.com/Path"


def test_collect_news_job_with_mock_feed(db: Session) -> None:
    seed_if_empty(db)
    # Keep only one source for the test
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

    def fake_fetch(url, **kwargs):
        return SAMPLE_RSS, 200, {"etag": "abc"}

    with patch("bagel.collectors.rss.fetch_text", side_effect=fake_fetch):
        result = run_collect_news(db)

    assert result["items_found"] == 3
    assert result["items_created"] >= 1
    assert result["status"] in {"SUCCESS", "PARTIAL"}
    # Excluded / no-include should be REJECTED; agent item CANDIDATE
    from bagel.domain.models import IntelItem

    items = db.query(IntelItem).all()
    statuses = {i.title: i.status for i in items}
    assert statuses.get("Open Source AI Agent Framework Release") == ItemStatus.CANDIDATE
    assert statuses.get("付费课程培训招生火热") == ItemStatus.REJECTED
