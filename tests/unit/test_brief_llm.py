"""Custom brief prompts: pool injection + LLM generation path."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from bagel.domain.enums import BriefKind, ItemStatus, ItemType, SourceType
from bagel.domain.models import Base, IntelItem
from bagel.services.brief_llm import format_item_pool, inject_item_pool
from bagel.services.monthly_brief import write_monthly_brief
from bagel.services.monthly_templates import render_monthly_brief
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.repositories import ItemRepository


@pytest.fixture()
def db(tmp_path):
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'brief_llm.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _add(db, **kwargs):
    repo = ItemRepository(db)
    item, _ = repo.upsert_from_normalized(
        item_type=kwargs.get("item_type", ItemType.NEWS),
        source_type=SourceType.RSS,
        source_id=None,
        title=kwargs["title"],
        url=kwargs["url"],
        summary=kwargs.get("summary", "摘要"),
        content=kwargs.get("content"),
        published_at=kwargs.get("published_at", datetime(2026, 8, 20, tzinfo=UTC)),
        category=kwargs.get("category", "大模型/LLM"),
        status=ItemStatus.CANDIDATE,
        score=kwargs.get("score", 2.0),
    )
    return item


def test_inject_item_pool_replaces_placeholder() -> None:
    out = inject_item_pool("请基于 {{新闻池}} 写汇报", "ITEM-A\nITEM-B")
    assert "ITEM-A" in out
    assert "{{新闻池}}" not in out


def test_inject_item_pool_appends_when_missing() -> None:
    out = inject_item_pool("重点讲推理成本", "POOL-BODY")
    assert "重点讲推理成本" in out
    assert "POOL-BODY" in out
    assert "素材池" in out


def test_format_item_pool_uses_content() -> None:
    item = IntelItem(
        title="成本新闻",
        url="https://example.com/c",
        canonical_url="https://example.com/c",
        item_type=ItemType.NEWS,
        source_type=SourceType.RSS,
        content_hash="h",
        status=ItemStatus.CANDIDATE,
        content="GPU 推理单价下降 30%，并给出 KV cache 优化细节。",
        summary="短摘要",
        category="大模型/LLM",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    pool = format_item_pool([item])
    assert "KV cache" in pool
    assert "短摘要" not in pool or "GPU 推理" in pool


def test_render_template_no_longer_dumps_custom_prompt() -> None:
    md = render_monthly_brief(
        kind=BriefKind.NEWS,
        year_month="2026-08",
        items=[],
        custom_prompt="重点讲 LLM 推理成本\n汇报对象：领导",
    )
    assert "自定义聚焦" not in md


def test_write_with_custom_prompt_uses_llm(db, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("ENABLE_LLM_SUMMARY", "true")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_MODEL", "demo")
    from bagel.settings import get_settings

    get_settings.cache_clear()

    _add(
        db,
        title="推理成本下降",
        url="https://example.com/cost",
        content="云厂商下调 API 推理单价，MoE 路由降低有效 token 成本。",
        score=3,
    )

    fake = MagicMock()
    fake.available = True
    fake.complete_text.return_value = (
        "# 领导汇报稿\n\n本周推理成本显著下降，详见素材。\n",
        None,
    )

    monkeypatch.setattr(
        "bagel.services.brief_llm.LlmClient",
        lambda *_a, **_k: fake,
    )

    bundle = write_monthly_brief(
        db,
        kind=BriefKind.NEWS,
        year_month="2026-08",
        custom_prompt="重点主题：LLM 推理成本\n汇报对象：公司领导\n请基于 {{新闻池}} 输出投屏终稿",
    )
    assert bundle.brief.metadata_["generation_mode"] == "llm"
    assert "领导汇报稿" in bundle.markdown
    assert "自定义聚焦" not in bundle.markdown
    assert fake.complete_text.called
    user_msg = fake.complete_text.call_args.kwargs["user"]
    assert "推理单价" in user_msg or "MoE" in user_msg


def test_write_custom_prompt_falls_back_without_llm(db, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LLM_ENABLED", "false")
    from bagel.settings import get_settings

    get_settings.cache_clear()
    _add(db, title="新闻A", url="https://example.com/a", content="正文足够长用于模板。", score=2)
    bundle = write_monthly_brief(
        db,
        kind=BriefKind.NEWS,
        year_month="2026-08",
        custom_prompt="重点讲成本",
    )
    assert bundle.brief.metadata_["generation_mode"] == "template_fallback"
    assert "未能经 LLM 生成" in bundle.markdown
    assert "发生了什么" in bundle.markdown
