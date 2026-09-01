"""Phase 2: repositories, raw evidence, upsert/dedup helpers."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, KeywordRuleType, SourceType
from bagel.domain.models import Base, IntelKeywordRule, IntelSource
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.repositories import (
    ItemRepository,
    KeywordRuleRepository,
    RawEvidenceRepository,
    SourceRepository,
    canonicalize_url,
    content_hash,
)


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


def test_canonicalize_url() -> None:
    assert canonicalize_url("HTTPS://Example.COM/Path/?utm_source=x") == "https://example.com/Path"


def test_content_hash_stable() -> None:
    a = content_hash("https://a.com/x", "Hello World")
    b = content_hash("https://a.com/x", "  hello   world ")
    assert a == b


def test_raw_evidence_and_item_upsert(db: Session) -> None:
    sources = SourceRepository(db)
    evidence_repo = RawEvidenceRepository(db)
    items = ItemRepository(db)

    source = sources.add(
        IntelSource(
            name="Test Feed",
            url="https://example.com/feed.xml",
            source_type=SourceType.RSS,
            region="CN",
        )
    )
    evidence = evidence_repo.create(
        source_type=SourceType.RSS,
        source_url=source.url,
        external_id="ext-1",
        raw_payload={"title": "AI Agent 开源发布", "link": "https://example.com/post/1"},
        http_status=200,
        collector_version="0.2.0",
    )
    assert evidence.raw_hash

    item, created = items.upsert_from_normalized(
        item_type=ItemType.NEWS,
        source_type=SourceType.RSS,
        source_id=source.id,
        title="AI Agent 开源发布",
        url="https://example.com/post/1?utm=1",
        summary="摘要",
        raw_evidence_id=evidence.id,
        status=ItemStatus.CANDIDATE,
        score=1.0,
    )
    assert created is True
    assert item.canonical_url == "https://example.com/post/1"
    assert item.raw_evidence_id == evidence.id

    item2, created2 = items.upsert_from_normalized(
        item_type=ItemType.NEWS,
        source_type=SourceType.RSS,
        source_id=source.id,
        title="AI Agent 开源发布",
        url="https://example.com/post/1",
        summary="摘要更新",
    )
    assert created2 is False
    assert item2.id == item.id
    assert item2.summary == "摘要更新"


def test_keyword_rules(db: Session) -> None:
    repo = KeywordRuleRepository(db)
    repo.add(IntelKeywordRule(keyword="培训招生", rule_type=KeywordRuleType.EXCLUDE))
    repo.add(IntelKeywordRule(keyword="AI Agent", rule_type=KeywordRuleType.INCLUDE, weight=2.0))
    rules = repo.list_enabled()
    assert len(rules) == 2


def test_favorite_keeps_candidate_status(db: Session) -> None:
    items = ItemRepository(db)
    item, _ = items.upsert_from_normalized(
        item_type=ItemType.NEWS,
        source_type=SourceType.RSS,
        source_id=None,
        title="Deep Read Candidate",
        url="https://example.com/deep",
        status=ItemStatus.CANDIDATE,
    )
    items.set_flags(item, is_favorite=True, is_top=True, is_deep_read=True)
    assert item.is_favorite and item.is_top and item.is_deep_read
    assert item.status == ItemStatus.CANDIDATE
