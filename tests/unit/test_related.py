"""Related-item scoring — summary core keywords."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, SourceType
from bagel.domain.models import Base
from bagel.services.related import (
    extract_core_keywords,
    find_related,
    keyword_similarity,
    supports_related,
)
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.repositories import ItemRepository


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'related.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _add(db: Session, **kwargs):
    repo = ItemRepository(db)
    item, _ = repo.upsert_from_normalized(
        item_type=kwargs.get("item_type", ItemType.NEWS),
        source_type=kwargs.get("source_type", SourceType.RSS),
        source_id=None,
        title=kwargs["title"],
        url=kwargs["url"],
        summary=kwargs.get("summary", "摘要"),
        author=kwargs.get("author"),
        published_at=kwargs.get("published_at", datetime(2026, 8, 20, tzinfo=UTC)),
        category=kwargs.get("category", "大模型/LLM"),
        status=ItemStatus.CANDIDATE,
        score=kwargs.get("score", 2.0),
        tags=kwargs.get("tags", []),
        topics=kwargs.get("topics", []),
        metadata=kwargs.get("metadata", {}),
    )
    return item


def test_supports_related_types():
    assert supports_related(ItemType.NEWS)
    assert supports_related(ItemType.PAPER)
    assert supports_related(ItemType.GITHUB_REPO)
    assert supports_related(ItemType.MEDIA_POST)


def test_extract_keywords_from_summary():
    keys = extract_core_keywords(
        "archify 用 typed JSON IR、九项检查与原子交付，把 AI 画架构图从碰运气变成可验收流水线。"
        "它强调 Agent 画图要有验收标准。"
    )
    assert "archify" in keys or "agent" in keys or "架构图" in keys or "验收" in keys
    assert "进行" not in keys
    assert "可以" not in keys


def test_summary_keywords_relate_even_if_titles_differ(db: Session):
    seed = _add(
        db,
        title="重磅！这个开源项目火了",
        url="https://example.com/n1",
        summary=(
            "archify 通过 typed JSON IR 与九项检查，把 Agent 生成架构图做成可验收流水线，"
            "强调失败可定位与原子交付。"
        ),
        tags=["AI", "教育"],
        category="其他",
    )
    related = _add(
        db,
        title="周末读物推荐（三）",
        url="https://example.com/n2",
        summary=(
            "另一篇文章拆解 archify：JSON IR、检查项与 Agent 架构图验收如何串成流水线。"
        ),
        tags=["misc"],
        category="行业动态",
    )
    noise = _add(
        db,
        title="今日热点速览",
        url="https://example.com/n3",
        summary="本地美食节开幕，游客增多，交通管制提示。",
        tags=["AI", "教育"],
        category="其他",
    )
    bundle = find_related(db, seed.id, limit=10)
    ids = {h.item.id for _, hits in bundle.groups for h in hits}
    assert related.id in ids
    assert noise.id not in ids
    assert any(title == "摘要关键词相近" for title, _ in bundle.groups)


def test_tags_alone_do_not_relate(db: Session):
    seed = _add(
        db,
        title="随便看看",
        url="https://example.com/p1",
        item_type=ItemType.PAPER,
        category="推理/训练",
        tags=["AI", "教育", "arxiv"],
        summary="We propose QGPINNs for nonlocal differential equations on quantum graphs using physics-informed neural networks.",
    )
    noise = _add(
        db,
        title="另一篇也随便",
        url="https://example.com/p2",
        item_type=ItemType.PAPER,
        category="推理/训练",
        tags=["AI", "教育", "arxiv"],
        summary="A cooking dataset for recipe generation and nutrition labeling.",
    )
    close = _add(
        db,
        title="标题完全不同也没关系",
        url="https://example.com/p3",
        item_type=ItemType.PAPER,
        category="其他",
        tags=["misc"],
        summary="Physics-informed neural networks on quantum graphs for nonlocal equations, related to QGPINNs.",
    )
    bundle = find_related(db, seed.id, limit=10)
    ids = {h.item.id for _, hits in bundle.groups for h in hits}
    assert noise.id not in ids
    assert close.id in ids


def test_same_author_other_works(db: Session):
    seed = _add(
        db,
        item_type=ItemType.PAPER,
        title="标题A",
        url="https://example.com/p1",
        author="Alice Zhang, Bob Li",
        category="推理/训练",
        summary="Physics-informed nets on graphs for engineering simulation.",
    )
    same_author = _add(
        db,
        item_type=ItemType.PAPER,
        title="标题B",
        url="https://example.com/p2",
        author="Alice Zhang",
        category="多模态",
        summary="A survey of vision transformers for medical imaging datasets.",
    )
    bundle = find_related(db, seed.id, limit=10)
    flat = [h for _, hits in bundle.groups for h in hits]
    assert any(h.item.id == same_author.id for h in flat)
    assert any("同一作者" in title for title, _ in bundle.groups)


def test_keyword_similarity_basic():
    a = extract_core_keywords("RAG 向量数据库与 embedding 召回评测")
    b = extract_core_keywords("检索增强 RAG：embedding 与向量数据库实践")
    sim, shared = keyword_similarity(a, b)
    assert sim > 0.12
    assert shared


def test_related_page_renders(db: Session, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    from fastapi.testclient import TestClient

    from bagel.main import create_app
    from bagel.settings import get_settings
    from bagel.storage.database import get_db

    get_settings.cache_clear()
    seed = _add(
        db,
        title="短标题1",
        url="https://example.com/n1",
        category="大模型/LLM",
        summary="开源大模型权重与评测脚本发布，benchmark 接近闭源旗舰。",
        tags=["LLM"],
    )
    _add(
        db,
        title="短标题2",
        url="https://example.com/n2",
        category="评测/基准",
        summary="开源大模型评测 benchmark 更新，权重下载与脚本复现说明。",
        tags=["other"],
    )
    app = create_app()

    def _override():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as client:
        page = client.get(f"/items/{seed.id}/related")
        assert page.status_code == 200
        assert "关联分析" in page.text
        assert "摘要" in page.text
        list_page = client.get("/news")
        assert list_page.status_code == 200
        assert f"/items/{seed.id}/related" in list_page.text
    app.dependency_overrides.clear()
    get_settings.cache_clear()
