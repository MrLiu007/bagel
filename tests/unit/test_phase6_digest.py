"""Phase 6: LLM summary + daily digest."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, JobStatus, SourceType
from bagel.domain.models import Base
from bagel.jobs.digest import run_build_digest, run_summarize_selected
from bagel.services.digest import build_daily_markdown
from bagel.services.llm import LlmClient, SummaryResult
from bagel.settings import Settings
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.repositories import ItemRepository


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'p6.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _add_selected(db: Session, title: str, url: str, **kwargs):
    repo = ItemRepository(db)
    item, _ = repo.upsert_from_normalized(
        item_type=kwargs.get("item_type", ItemType.NEWS),
        source_type=SourceType.RSS,
        source_id=None,
        title=title,
        url=url,
        summary=kwargs.get("summary", "原始摘要"),
        status=ItemStatus.SELECTED,
        score=kwargs.get("score", 1.0),
        tags=kwargs.get("tags", []),
        metadata=kwargs.get("metadata", {}),
    )
    if kwargs.get("is_top") or kwargs.get("is_deep_read"):
        repo.set_flags(
            item,
            is_top=True if kwargs.get("is_top") else None,
            is_deep_read=True if kwargs.get("is_deep_read") else None,
        )
    return item


def test_summarize_selected_does_not_overwrite_raw(db: Session) -> None:
    item = _add_selected(db, "Original Title", "https://example.com/orig")
    original_title = item.title
    original_url = item.url

    fake = SummaryResult(
        summary="这是一份 80 到 150 字左右的中文摘要，用于说明该开源 Agent 框架的价值。",
        why="它降低了 RAG Agent 的接入成本。",
        audience="技术",
        title_zh="开源 Agent 框架发布",
    )
    settings = Settings(
        llm_enabled=True,
        enable_llm_summary=True,
        llm_base_url="http://x",
        llm_model="m",
    )
    with patch.object(LlmClient, "available", True), patch.object(
        LlmClient, "summarize_item", return_value=fake
    ):
        result = run_summarize_selected(db, settings)

    assert result["items_updated"] == 1
    db.refresh(item)
    assert item.title == original_title
    assert item.url == original_url
    assert item.llm_summary.startswith("这是一份")
    assert item.llm_title_zh == "开源 Agent 框架发布"
    assert item.status == ItemStatus.SUMMARIZED


def test_build_daily_digest_markdown_and_files(db: Session, tmp_path) -> None:
    _add_selected(db, "CN News", "https://example.com/cn", tags=["中国"], is_top=True, score=5)
    _add_selected(
        db,
        "Global News",
        "https://example.com/global",
        score=3,
        metadata={"region": "GLOBAL"},
    )
    _add_selected(
        db,
        "acme/agent",
        "https://github.com/acme/agent",
        item_type=ItemType.GITHUB_REPO,
        score=4,
    )
    _add_selected(
        db,
        "acme/agent v1",
        "https://github.com/acme/agent/releases/tag/v1",
        item_type=ItemType.GITHUB_RELEASE,
        is_deep_read=True,
    )

    settings = Settings(data_dir=str(tmp_path / "data"))
    result = run_build_digest(db, settings)
    assert result["status"] == JobStatus.SUCCESS
    md = result["markdown"]
    assert "# 贝果日报" in md
    assert "## 今日最重要 5 条" in md
    assert "## 国内 AI" in md
    assert "## 海外 AI" in md
    assert "## GitHub 新项目" in md
    assert "## GitHub 重要更新" in md
    assert "## 深度阅读" in md
    assert list((tmp_path / "data" / "digests").glob("*.md"))
    assert list((tmp_path / "data" / "digests").glob("*.html"))


def test_digest_template_helper() -> None:
    class Fake:
        title = "A"
        url = "https://a"
        item_type = ItemType.NEWS
        is_top = True
        is_deep_read = False
        score = 1
        llm_title_zh = None
        llm_summary = None
        llm_why = None
        summary = "s"
        tags = []
        metadata_ = {}
        language = None

    md = build_daily_markdown([Fake()])  # type: ignore[list-item]
    assert "今日最重要" in md
