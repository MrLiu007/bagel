"""Shared catalog owner repair + paper source defaults."""

from __future__ import annotations

from bagel.domain.enums import ItemType, Region, SourceType
from bagel.domain.models import Base, IntelItem, IntelSource
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.seed import repair_paper_sources, repair_shared_catalog_owners


def test_repair_shared_catalog_owners(tmp_path) -> None:
    from sqlalchemy import select

    from bagel.domain.models import AppUser

    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'own.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    user = AppUser(username="tester", password_hash="x", is_active=True, is_admin=False)
    session.add(user)
    session.flush()
    owner = user.id
    session.add(
        IntelItem(
            item_type=ItemType.EDUCATION,
            source_type=SourceType.EDUCATION,
            owner_id=owner,
            title="MIT course",
            url="https://example.com/edu/1",
            canonical_url="https://example.com/edu/1",
            content_hash="h1",
            status="CANDIDATE",
        )
    )
    session.add(
        IntelItem(
            item_type=ItemType.MODEL,
            source_type=SourceType.MODEL,
            owner_id=owner,
            title="personal model",
            url="https://example.com/m/1",
            canonical_url="https://example.com/m/1",
            content_hash="h2",
            status="CANDIDATE",
        )
    )
    session.commit()
    n = repair_shared_catalog_owners(session)
    session.commit()
    assert n == 1
    edu = session.scalars(
        select(IntelItem).where(IntelItem.item_type == ItemType.EDUCATION)
    ).one()
    model = session.scalars(
        select(IntelItem).where(IntelItem.item_type == ItemType.MODEL)
    ).one()
    assert edu.owner_id is None
    assert model.owner_id == owner
    session.close()
    engine.dispose()


def test_repair_paper_sources_disables_s2_and_removes_hf(tmp_path) -> None:
    from sqlalchemy import select

    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'paper.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    session.add(
        IntelSource(
            name="Semantic Scholar LLM",
            url="s2:large language model",
            source_type=SourceType.PAPER,
            region=Region.GLOBAL,
            enabled=True,
        )
    )
    session.add(
        IntelSource(
            name="arXiv cs.AI",
            url="arxiv:cs.AI",
            source_type=SourceType.PAPER,
            region=Region.GLOBAL,
            enabled=True,
        )
    )
    hf = IntelSource(
        name="Hugging Face Papers",
        url="hf:daily",
        source_type=SourceType.PAPER,
        region=Region.GLOBAL,
        enabled=True,
    )
    session.add(hf)
    session.flush()
    session.add(
        IntelItem(
            item_type=ItemType.PAPER,
            source_type=SourceType.PAPER,
            source_id=hf.id,
            title="HF curated paper",
            url="https://arxiv.org/abs/2401.00001",
            canonical_url="https://arxiv.org/abs/2401.00001",
            content_hash="h-hf",
            status="CANDIDATE",
        )
    )
    session.commit()
    n = repair_paper_sources(session)
    session.commit()
    assert n == 2
    rows = {r.name: r for r in session.scalars(select(IntelSource)).all()}
    assert "Hugging Face Papers" not in rows
    assert rows["Semantic Scholar LLM"].enabled is False
    assert rows["arXiv cs.AI"].enabled is True
    paper = session.scalars(select(IntelItem)).one()
    assert paper.source_id is None
    session.close()
    engine.dispose()


def test_repair_stock_sources_removes_cn_rsshub(tmp_path) -> None:
    from sqlalchemy import select

    from bagel.storage.seed import repair_stock_sources

    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'stock.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    session.add(
        IntelSource(
            name="财联社电报 (RSSHub)",
            url="/cls/telegraph",
            source_type=SourceType.STOCK,
            region=Region.CN,
            enabled=True,
        )
    )
    session.add(
        IntelSource(
            name="Yahoo Finance",
            url="https://finance.yahoo.com/news/rssindex",
            source_type=SourceType.STOCK,
            region=Region.GLOBAL,
            enabled=True,
        )
    )
    session.commit()
    n = repair_stock_sources(session)
    session.commit()
    assert n == 1
    rows = list(session.scalars(select(IntelSource)).all())
    assert len(rows) == 1
    assert rows[0].name == "Yahoo Finance"
    session.close()
    engine.dispose()


def test_repair_github_queries_keeps_single(tmp_path) -> None:
    from sqlalchemy import select

    from bagel.domain.models import IntelGithubQuery
    from bagel.storage.seed import DEFAULT_GITHUB_QUERIES, repair_github_queries

    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'gq.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    session.add(IntelGithubQuery(name="LLM", query="llm stars:>50", enabled=True))
    session.add(IntelGithubQuery(name="Agent", query="agent stars:>50", enabled=True))
    session.commit()
    n = repair_github_queries(session)
    session.commit()
    assert n >= 1
    rows = list(session.scalars(select(IntelGithubQuery)).all())
    assert len(rows) == 1
    assert rows[0].name == "GitHub"
    assert rows[0].query == DEFAULT_GITHUB_QUERIES[0][1]
    session.close()
    engine.dispose()
