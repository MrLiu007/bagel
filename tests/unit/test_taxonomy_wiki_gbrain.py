"""Taxonomy loader, wiki compile index, and taxonomy-aware GBrain."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, SourceType
from bagel.domain.models import Base, IntelItem, WikiEdge, WikiPage
from bagel.services.gbrain import adapt_intel_item, build_gbrain_graph, build_knowledge_graph
from bagel.services.wiki_compile import compile_wiki, topics_for_item
from bagel.settings import get_settings
from bagel.storage.database import get_engine, get_session_factory
from bagel.taxonomy import load_taxonomy, match_topics, validate_taxonomy
from bagel.taxonomy.loader import clear_taxonomy_cache


def test_taxonomy_seed_valid() -> None:
    clear_taxonomy_cache()
    tax = load_taxonomy()
    validate_taxonomy(tax)
    assert len(tax.topics) >= 10
    assert len(tax.dependencies) >= 5
    assert "tp_agent" in tax.topics
    assert any(d.topic_id == "tp_agent" and d.prerequisite_id == "tp_llm" for d in tax.dependencies)


def test_match_topics_prefers_aliases_and_category() -> None:
    clear_taxonomy_cache()
    hits = match_topics(
        "Building a multi-agent RAG pipeline with tool use",
        category="Agent",
        item_type=ItemType.NEWS,
    )
    ids = {t.id for t in hits}
    assert "tp_agent" in ids
    assert "tp_rag" in ids or "tp_llm" in ids


def test_gbrain_uses_topics_not_noise_tags() -> None:
    clear_taxonomy_cache()
    news = IntelItem(
        item_type=ItemType.NEWS,
        source_type="RSS",
        title="OpenAI Agent framework release",
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        content_hash="g1",
        status=ItemStatus.CANDIDATE,
        summary="LLM agent with tool calling and planning.",
        tags=["xxnoise", "tmp"],
        category="Agent",
        published_at=datetime.now(UTC),
    )
    paper = IntelItem(
        item_type=ItemType.PAPER,
        source_type=SourceType.PAPER,
        title="Retrieval Augmented Generation survey",
        url="https://example.com/p",
        canonical_url="https://example.com/p",
        content_hash="g2",
        status=ItemStatus.CANDIDATE,
        summary="RAG systems over vector databases.",
        category="RAG",
        published_at=datetime.now(UTC),
    )
    edu = IntelItem(
        item_type=ItemType.EDUCATION,
        source_type=SourceType.EDUCATION,
        title="MIT OCW Intro AI",
        url="https://example.com/e",
        canonical_url="https://example.com/e",
        content_hash="g3",
        status=ItemStatus.CANDIDATE,
        summary="OpenCourseWare artificial intelligence course.",
        category="教育应用",
        published_at=datetime.now(UTC),
        metadata_={"institution": "MIT"},
    )
    wikis = [adapt_intel_item(x) for x in (news, paper, edu)]
    assert any(t.startswith("tp_") for t in wikis[0].topic_ids)
    graph = build_gbrain_graph(wikis)
    kinds = {n.kind for n in graph.nodes}
    assert "item" in kinds
    assert "topic" in kinds
    assert "type" in kinds
    type_labels = {n.label for n in graph.nodes if n.kind == "type"}
    assert type_labels & {"新闻", "论文", "教育"}
    assert not any(n.kind == "tag" and n.label == "xxnoise" for n in graph.nodes)
    assert any(e.relation == "prerequisite" for e in graph.edges)
    assert graph.echarts["stats"]["topics"] >= 1
    assert graph.echarts["stats"]["resources"] >= 1
    assert "items" not in graph.echarts["stats"]


def test_wiki_compile_md_and_db_index(tmp_path, monkeypatch) -> None:
    clear_taxonomy_cache()
    monkeypatch.setenv("WIKI_DIR", str(tmp_path / "wiki"))
    get_settings.cache_clear()
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'w.db'}")
    Base.metadata.create_all(engine)
    session: Session = get_session_factory(engine)()
    session.add(
        IntelItem(
            item_type=ItemType.NEWS,
            source_type="RSS",
            title="DeepSeek LLM open source release",
            url="https://example.com/ds",
            canonical_url="https://example.com/ds",
            content_hash="wc1",
            status=ItemStatus.CANDIDATE,
            summary="Open source large language model release on GitHub.",
            category="开源发布",
            published_at=datetime.now(UTC),
        )
    )
    session.commit()

    result = compile_wiki(session, limit=50)
    session.commit()
    assert result["topics_written"] >= 1
    topic_files = list((tmp_path / "wiki" / "topics").glob("tp_*.md"))
    assert topic_files
    assert (tmp_path / "wiki" / "index.md").exists()
    assert (tmp_path / "wiki" / "log.md").exists()
    pages = list(session.scalars(select(WikiPage)).all())
    assert any(p.kind == "topic" for p in pages)
    assert any(p.kind == "item" for p in pages)
    edges = list(session.scalars(select(WikiEdge)).all())
    assert any(e.relation == "prerequisite" for e in edges)
    assert any(e.relation == "about" for e in edges)

    graph = build_knowledge_graph(session)
    assert graph.echarts["stats"]["resources"] >= 1
    assert graph.echarts["stats"]["topics"] >= 1
    assert "items" not in graph.echarts["stats"]
    assert any("fy" in n for n in graph.echarts["nodes"])

    item = session.scalars(select(IntelItem)).first()
    assert item is not None
    assert topics_for_item(item)

    session.close()
    engine.dispose()
    get_settings.cache_clear()
    clear_taxonomy_cache()
