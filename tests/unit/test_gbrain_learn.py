"""GBrain learn cards, subtopics, and subject filters."""

from __future__ import annotations

from datetime import UTC, datetime

from bagel.domain.enums import ItemStatus, ItemType
from bagel.domain.models import Base, GbrainLearnEvent, IntelItem
from bagel.services.gbrain import adapt_intel_item, build_gbrain_graph
from bagel.services.gbrain_learn import knowledge_card, record_learn, review_summary
from bagel.storage.database import get_engine, get_session_factory
from bagel.taxonomy import children_of, clear_taxonomy_cache, load_taxonomy


def test_subtopics_and_parent_links() -> None:
    clear_taxonomy_cache()
    tax = load_taxonomy()
    assert tax.get("tp_rag_hybrid") is not None
    assert tax.get("tp_rag_hybrid").parent_id == "tp_rag"
    kids = children_of(tax, "tp_rag")
    assert {c.id for c in kids} >= {"tp_rag_hybrid", "tp_rag_graph"}
    assert any(d.topic_id == "tp_agent_tools" for d in tax.dependencies)


def test_knowledge_card_and_learn_events(tmp_path) -> None:
    clear_taxonomy_cache()
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'learn.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    session.add(
        IntelItem(
            item_type=ItemType.NEWS,
            source_type="RSS",
            title="GraphRAG hybrid retrieval release",
            url="https://example.com/gr",
            canonical_url="https://example.com/gr",
            content_hash="learn1",
            status=ItemStatus.CANDIDATE,
            summary="GraphRAG and hybrid search for RAG systems.",
            category="RAG",
            published_at=datetime.now(UTC),
        )
    )
    session.commit()

    from sqlalchemy import select

    item = session.scalars(select(IntelItem)).first()
    assert item is not None

    card = knowledge_card(session, "topic:tp_rag")
    assert card is not None
    assert card["title"] == "RAG"
    assert card.get("resources") or card.get("related_resources") is not None
    assert any(b["id"] == "tp_llm" for b in card["builds_on"])

    item_card = knowledge_card(session, f"item:{item.id}")
    assert item_card is not None
    assert item_card["url"].startswith("https://")
    assert item_card["summary"]
    assert item_card.get("primary_cta") == "open_url"

    record_learn(session, node_key="topic:tp_rag", action="view")
    record_learn(session, node_key=f"item:{item.id}", action="focus")
    session.commit()
    rev = review_summary(session, days=14)
    assert rev["event_count"] >= 2
    assert rev["unique_nodes"] >= 1

    graph = build_gbrain_graph([adapt_intel_item(item)])
    subjects = graph.echarts["stats"].get("subjects") or []
    keys = [s["key"] for s in subjects]
    assert keys == ["新闻", "GitHub", "教育", "论文", "模型", "股票", "自媒体", "微信"]
    assert subjects[1]["label"] == "GitHub项目"
    assert "AI" not in keys

    session.close()
    engine.dispose()
    clear_taxonomy_cache()
