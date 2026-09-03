"""Monthly sharing briefs — kind-specific templates + export."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bagel.domain.enums import BriefKind, ItemStatus, ItemType, SourceType
from bagel.domain.models import Base
from bagel.main import create_app
from bagel.services.monthly_brief import write_monthly_brief
from bagel.services.monthly_templates import render_monthly_brief
from bagel.storage.database import get_db, get_engine, get_session_factory
from bagel.storage.repositories import ItemRepository


@pytest.fixture()
def db(tmp_path) -> Session:
    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'brief.db'}")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
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
    from bagel.settings import get_settings

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


def _add(db: Session, **kwargs):
    repo = ItemRepository(db)
    item, _ = repo.upsert_from_normalized(
        item_type=kwargs.get("item_type", ItemType.NEWS),
        source_type=SourceType.RSS,
        source_id=None,
        title=kwargs["title"],
        url=kwargs["url"],
        summary=kwargs.get("summary", "摘要"),
        published_at=kwargs.get("published_at", datetime(2026, 8, 20, tzinfo=UTC)),
        category=kwargs.get("category", "大模型/LLM"),
        status=ItemStatus.CANDIDATE,
        score=kwargs.get("score", 2.0),
        tags=kwargs.get("tags", ["LLM"]),
    )
    if "llm_why" in kwargs:
        item.llm_why = kwargs["llm_why"]
    if "llm_summary" in kwargs:
        item.llm_summary = kwargs["llm_summary"]
    return item


def test_markdown_mermaid_becomes_div():
    from bagel.web.routes.briefs import markdown_to_article_html

    html = markdown_to_article_html("```mermaid\npie title T\n  \"A\" : 1\n```\n")
    assert 'class="mermaid"' in html
    assert "<pre>" not in html
    assert "pie title T" in html


def test_markdown_lists_wrap_ul():
    from bagel.web.routes.briefs import markdown_to_article_html

    html = markdown_to_article_html("- one\n- two\n\nDone\n")
    assert "<ul>" in html and "</ul>" in html
    assert "<li>one</li>" in html


def test_markdown_table_scroll_and_bare_url():
    from bagel.web.routes.briefs import markdown_to_article_html

    md = (
        "| # | 链接 |\n| --- | --- |\n"
        "| 1 | https://www.infoq.cn/article/ztbou1CqjAdzrT6GNSKV?utm_source=rss |\n"
    )
    html = markdown_to_article_html(md)
    assert 'class="table-scroll"' in html
    assert "infoq.cn" in html
    assert "utm_source" not in html.split(">", 1)[-1] or "infoq.cn" in html
    assert 'href="https://www.infoq.cn/article/' in html


def test_link_table_uses_short_markdown_links():
    from bagel.domain.models import IntelItem
    from bagel.services.monthly_templates import _link_table

    item = IntelItem(
        title="Cloudflare OS",
        url="https://www.infoq.cn/article/ztbou1CqjAdzrT6GNSKV?utm_source=rss",
        canonical_url="https://www.infoq.cn/article/ztbou1CqjAdzrT6GNSKV?utm_source=rss",
        item_type="NEWS",
        source_type="RSS",
        content_hash="h1",
        status="CANDIDATE",
    )
    lines = _link_table([item])
    joined = "\n".join(lines)
    assert "[infoq.cn](https://www.infoq.cn/article/" in joined
    assert joined.count("utm_source") == 1  # only inside URL target, not as cell text alone


def test_template_news_structure():
    md = render_monthly_brief(kind=BriefKind.NEWS, year_month="2026-08", items=[])
    assert "讲解口径（新闻）" in md
    assert "发生了什么" in md or "精选新闻" in md
    assert "费曼" not in md
    assert "苏格拉底" not in md
    assert "学员" not in md


def test_science_template_share_guide():
    md = render_monthly_brief(kind=BriefKind.SCIENCE, year_month="2026-08", items=[])
    assert "论文 / papers" in md
    assert "讲解口径（论文）" in md
    assert "原文链接清单" in md
    assert "学员" not in md


def test_media_template_like_news():
    md = render_monthly_brief(kind=BriefKind.MEDIA, year_month="2026-08", items=[])
    assert "自媒体" in md
    assert "讲解口径（自媒体）" in md
    assert "原文链接清单" in md


def test_news_entry_has_contrast_and_example(db: Session):
    item = _add(
        db,
        title="开源大模型发布",
        url="https://example.com/n1",
        score=3,
        summary="某机构发布开源权重与评测脚本，编程基准接近闭源旗舰。",
        category="大模型/LLM",
    )
    md = render_monthly_brief(kind=BriefKind.NEWS, year_month="2026-08", items=[item])
    assert "发生了什么" in md
    assert "某机构发布开源权重" in md
    assert "增量对比" in md
    assert "例子" in md
    assert "对我们意味着什么" in md
    assert "让学员" not in md
    assert "用白话讲透（费曼）" not in md


def test_science_no_duplicate_sections(db: Session):
    item = _add(
        db,
        item_type=ItemType.PAPER,
        title="QGPINNs on Quantum Graphs",
        url="https://example.com/p1",
        score=3,
        summary="We propose QGPINNs for nonlocal equations on quantum graphs.",
        category="推理/训练",
        llm_why="科普落脚：该工作的核心思想能否转化为教学项目或课程案例？是否有助于降低学员理解前沿技术的门槛？",
    )
    md = render_monthly_brief(kind=BriefKind.SCIENCE, year_month="2026-08", items=[item])
    assert "要解决什么问题" in md
    assert "做法与朴素方法有何不同" in md
    assert "直观例子" in md
    assert "科普落脚" not in md
    # Sections must not repeat the same paragraph.
    assert md.count("能否转化为教学项目") == 0
    assert "QGPINNs" in md or "quantum graphs" in md.lower() or "原文摘要" in md


def test_github_has_migration_sections(db: Session):
    item = _add(
        db,
        item_type=ItemType.GITHUB_REPO,
        title="archify",
        url="https://github.com/example/archify",
        score=4,
        summary="archify 用 typed JSON IR 与九项检查，把画架构图变成可验收流水线。",
        category="Agent",
    )
    md = render_monthly_brief(kind=BriefKind.GITHUB, year_month="2026-08", items=[item])
    assert "项目是什么" in md
    assert "巧妙之处" in md
    assert "最小上手" in md
    assert "可迁移启发" in md
    assert "archify 用 typed JSON IR" in md


def test_news_tab_link_from_github_page(client: TestClient, db: Session):
    page = client.get("/briefs/github")
    assert page.status_code == 200
    assert 'href="/briefs?period=' in page.text
    assert "新闻总结" in page.text


def test_collect_month_uses_published_at_only(db: Session):
    from bagel.services.monthly_brief import collect_month_items

    _add(
        db,
        title="七月旧闻",
        url="https://example.com/old",
        published_at=datetime(2026, 7, 15, tzinfo=UTC),
        score=9,
    )
    _add(
        db,
        title="八月新闻",
        url="https://example.com/aug",
        published_at=datetime(2026, 8, 10, tzinfo=UTC),
        score=1,
        summary="八月发布的专业向动态。",
    )
    items = collect_month_items(db, kind=BriefKind.NEWS, year_month="2026-08")
    titles = {i.title for i in items}
    assert "八月新闻" in titles
    assert "七月旧闻" not in titles


def test_write_and_export_monthly_brief(client: TestClient, db: Session, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    from bagel.settings import get_settings

    get_settings.cache_clear()

    _add(
        db,
        title="开源大模型发布",
        url="https://example.com/n1",
        score=3,
        summary="某机构发布开源大模型，宣称在编程与推理基准上接近闭源旗舰，并给出权重与评测脚本。",
    )
    _add(
        db,
        title="Agent 框架更新",
        url="https://example.com/n2",
        category="Agent",
        score=2.5,
        summary="新版本加入工具调用追踪与可回放日志，强调多 Agent 协作中的失败可定位。",
    )
    bundle = write_monthly_brief(db, kind=BriefKind.NEWS, year_month="2026-08")
    assert bundle.item_count == 2
    assert bundle.path_md.exists()
    assert "发生了什么" in bundle.markdown
    assert "〔 1 / 2 〕" in bundle.markdown
    assert "受众" not in bundle.markdown
    assert "原文链接清单" in bundle.markdown

    page = client.get("/briefs/news?month=2026-08")
    assert page.status_code == 200
    assert "新闻总结" in page.text
    assert "开源大模型发布" in page.text

    export = client.get("/briefs/news/2026-08.md")
    assert export.status_code == 200
    assert "发生了什么" in export.text

    present = client.get("/briefs/news/2026-08/present")
    assert present.status_code == 200
    assert "brief-body" in present.text
    assert "开源大模型发布" in present.text
    assert "mermaid" in present.text.lower() or "发生了什么" in present.text

    html_export = client.get("/briefs/news/2026-08.html")
    assert html_export.status_code == 200
    assert "attachment" in (html_export.headers.get("content-disposition") or "")
    assert "brief-body" in html_export.text

    gen = client.post(
        "/briefs/generate",
        data={"kind": "NEWS", "year_month": "2026-08"},
        follow_redirects=False,
    )
    assert gen.status_code == 303
