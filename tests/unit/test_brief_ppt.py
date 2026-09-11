"""PPT mode for brief projection (reveal.js slides)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bagel.domain.enums import BriefKind, ItemStatus, ItemType, SourceType
from bagel.domain.models import Base
from bagel.main import create_app
from bagel.services.brief_ppt import (
    article_html_to_slides,
    build_brief_ppt_html,
    build_ppt_loading_html,
    compose_ppt_slides,
    get_or_build_ppt_slides,
    load_ppt_slides_cache,
    ppt_content_fingerprint,
)
from bagel.services.monthly_brief import write_monthly_brief
from bagel.settings import get_settings
from bagel.storage.database import get_db, get_engine, get_session_factory
from bagel.storage.repositories import ItemRepository
from bagel.web.routes.briefs import markdown_to_article_html


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'ppt.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db: Session, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    app = create_app()

    def _override():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_compose_ppt_slides_rewrites_into_bullets() -> None:
    html_body = """
<h1>九月新闻总结</h1>
<blockquote>投屏终稿</blockquote>
<h2>投屏摘要</h2>
<ul><li>主线判断：成本下降</li><li>开源权重增多</li><li>推理链路缩短</li></ul>
<p>还有一段很长的说明文字。第二句补充细节。第三句再讲一点结论。</p>
<h2>精选新闻</h2>
<hr class="item-sep"/>
<p class="item-index">〔 1 / 2 〕</p>
<h3 class="brief-item-title">条目一</h3>
<p>某机构发布开源权重与评测脚本，便于复现。社区反响积极。后续计划开源训练代码。</p>
<hr class="item-sep"/>
<p class="item-index">〔 2 / 2 〕</p>
<h3 class="brief-item-title">条目二</h3>
<p>正文二。第二句。</p>
"""
    slides = compose_ppt_slides(html_body)
    assert len(slides) >= 3
    assert "九月新闻总结" in slides[0]
    assert any("ppt-bullets" in s for s in slides)
    assert all(s.count("<p>") < 8 for s in slides)
    joined = "\n".join(slides)
    assert "条目一" in joined
    assert "条目二" in joined


def test_article_html_to_slides_rules_without_llm() -> None:
    html_body = "<h1>标题</h1><h2>第一节</h2><ul><li>甲</li><li>乙</li></ul>"
    slides = article_html_to_slides(html_body, use_llm=False)
    assert slides[0].startswith("<h1>")
    assert any("ppt-bullets" in s for s in slides)


def test_build_brief_ppt_html_uses_reveal() -> None:
    article = markdown_to_article_html(
        "# 标题\n\n## 第一节\n\n内容甲。第二句。\n\n## 第二节\n\n内容乙。\n"
    )
    doc = build_brief_ppt_html(
        title="测试 PPT",
        article_html=article,
        back_url="/briefs",
        doc_mode_url="/briefs/news/2026-08/present",
        export_html_url="/briefs/news/2026-08.html",
        export_md_url="/briefs/news/2026-08.md",
        meta_line="demo",
        use_llm=False,
    )
    assert "reveal.js@5.1.0" in doc
    assert 'class="reveal"' in doc
    assert "ppt-prev" in doc and "ppt-next" in doc
    assert "文档模式" in doc
    assert doc.count('class="bagel-slide"') >= 2
    assert "ppt-bullets" in doc
    assert 'class="slide-inner"' in doc
    assert "justify-content: center" in doc
    assert "center: false" in doc
    assert 'sec.style.top = "0px"' in doc


def test_multi_slide_bodies_have_content() -> None:
    html_body = """
<h1>月报</h1>
<h2>第一节</h2>
<ul><li>要点甲很长一句</li><li>要点乙很长一句</li></ul>
<h2>第二节</h2>
<ul><li>要点丙很长一句</li><li>要点丁很长一句</li></ul>
"""
    slides = compose_ppt_slides(html_body)
    assert len(slides) >= 3
    # Beyond title slide, each body slide must carry bullets or explicit empty note.
    for body in slides[1:]:
        assert ("ppt-bullets" in body) or ("ppt-kicker" in body)
        assert len(body) > 20


def test_build_ppt_loading_html() -> None:
    doc = build_ppt_loading_html(
        title="演示",
        build_url="/briefs/news/2026-08/present?mode=ppt&built=1",
        back_url="/briefs",
        meta_line="8 条",
    )
    assert "正在生成 PPT" in doc
    assert "built=1" in doc
    assert "ppt-loader" in doc
    assert "首次生成后会缓存" in doc


def test_ppt_cache_reuse(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    settings = get_settings()
    article = "<h1>标题</h1><h2>节</h2><ul><li>甲</li><li>乙</li></ul>"
    fp = ppt_content_fingerprint(markdown="# 标题\n", title="t", item_count=1)
    slides1, cached1 = get_or_build_ppt_slides(
        article, brief_id="brief-1", fingerprint=fp, use_llm=False, settings=settings
    )
    assert cached1 is False
    assert slides1
    slides2, cached2 = get_or_build_ppt_slides(
        article, brief_id="brief-1", fingerprint=fp, use_llm=False, settings=settings
    )
    assert cached2 is True
    assert slides2 == slides1
    assert load_ppt_slides_cache("brief-1", "other-fp", settings=settings) is None
    slides3, cached3 = get_or_build_ppt_slides(
        article,
        brief_id="brief-1",
        fingerprint=fp,
        use_llm=False,
        force=True,
        settings=settings,
    )
    assert cached3 is False
    assert slides3


def test_present_ppt_route(client: TestClient, db: Session) -> None:
    repo = ItemRepository(db)
    repo.upsert_from_normalized(
        item_type=ItemType.NEWS,
        source_type=SourceType.RSS,
        source_id=None,
        title="开源大模型发布",
        url="https://example.com/n1",
        summary="某机构发布开源权重。",
        content="某机构发布开源权重与评测脚本，便于复现。",
        published_at=datetime(2026, 8, 20, tzinfo=UTC),
        category="大模型/LLM",
        status=ItemStatus.CANDIDATE,
        score=3.0,
    )
    write_monthly_brief(db, kind=BriefKind.NEWS, year_month="2026-08")
    db.commit()

    loading = client.get("/briefs/news/2026-08/present?mode=ppt")
    assert loading.status_code == 200
    assert "正在生成 PPT" in loading.text
    assert "built=1" in loading.text

    page = client.get("/briefs/news/2026-08/present?mode=ppt&built=1")
    assert page.status_code == 200
    assert "reveal.js" in page.text
    assert "上一页" in page.text
    assert "下一页" in page.text
    assert "bagel-slide" in page.text
    assert "ppt-bullets" in page.text or "<h1>" in page.text
    assert "重新生成" in page.text

    # Second open: cache hit — skip loader
    again = client.get("/briefs/news/2026-08/present?mode=ppt")
    assert again.status_code == 200
    assert "正在生成 PPT" not in again.text
    assert "reveal.js" in again.text
    assert "缓存" in again.text

    rebuild = client.get("/briefs/news/2026-08/present?mode=ppt&rebuild=1")
    assert rebuild.status_code == 200
    assert "正在生成 PPT" in rebuild.text
    assert "rebuild=1" in rebuild.text

    doc = client.get("/briefs/news/2026-08/present")
    assert doc.status_code == 200
    assert "PPT 模式" in doc.text

    hub = client.get("/briefs/news?month=2026-08")
    assert hub.status_code == 200
    assert "present?mode=ppt" in hub.text
