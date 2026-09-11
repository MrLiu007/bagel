"""Content-first body selection for weekly/monthly briefs."""

from __future__ import annotations

from bagel.domain.enums import ItemType
from bagel.domain.models import IntelItem
from bagel.pipeline.textutil import coalesce_item_content
from bagel.services.monthly_templates import _body_text, _prioritize_by_prompt, render_monthly_brief
from bagel.domain.enums import BriefKind


def _item(**kwargs) -> IntelItem:
    defaults = dict(
        title="t",
        url="https://example.com/x",
        canonical_url="https://example.com/x",
        item_type=ItemType.NEWS,
        source_type="RSS",
        content_hash="h",
        status="CANDIDATE",
    )
    defaults.update(kwargs)
    return IntelItem(**defaults)


def test_coalesce_item_content_prefers_content_then_summary() -> None:
    assert coalesce_item_content("<p>full body</p>", "short") == "<p>full body</p>"
    assert coalesce_item_content(None, "only summary long enough") == "only summary long enough"
    assert coalesce_item_content("", "") is None


def test_news_body_prefers_content_over_longer_llm_summary() -> None:
    item = _item(
        content=(
            "厂商今日发布开源权重与完整评测脚本，编程基准接近闭源旗舰，"
            "并公开训练配方、复现命令与许可说明，便于团队对照落地。"
        ),
        summary="短摘要。",
        llm_summary="这是一段更长的 LLM 改写摘要，如果按最长字段会错误地压过正文事实细节。" * 3,
    )
    body = _body_text(item)
    assert "开源权重与完整评测脚本" in body
    assert "LLM 改写摘要" not in body


def test_news_falls_back_to_summary_when_content_empty() -> None:
    item = _item(content=None, summary="采集摘要：模型开放权重与 API，并给出基准数字。", llm_summary="LLM 一句。")
    assert "采集摘要" in _body_text(item)


def test_short_content_teaser_falls_through_to_summary() -> None:
    item = _item(
        content="Read more",
        summary="完整报道：研究团队公布了新的基准与可复现实验设置，涵盖多语言评测。",
        llm_summary="",
    )
    body = _body_text(item)
    assert "完整报道" in body


def test_paper_prefers_abstract_summary_over_parsed_front_matter() -> None:
    item = _item(
        item_type=ItemType.PAPER,
        summary="We propose a sparse attention variant that cuts KV cache by 40%.",
        content="# Title\n\nCopyright 2026\n\nAll rights reserved.\n\n" + ("pad " * 400),
        llm_summary="LLM 压缩版。",
    )
    body = _body_text(item)
    assert "sparse attention" in body
    assert "Copyright" not in body


def test_prioritize_prompt_matches_content() -> None:
    a = _item(title="A", summary="无关", content="本周讨论 RAG 切块与召回", url="https://e.com/a", content_hash="a")
    b = _item(title="B", summary="无关", content="纯产品发布会花絮", url="https://e.com/b", content_hash="b")
    ordered = _prioritize_by_prompt([a, b], "RAG 召回")
    assert ordered[0].title == "A"


def test_render_news_includes_content_not_only_short_summary() -> None:
    item = _item(
        title="开源大模型发布",
        content="某机构发布开源权重、训练配方与评测脚本，编程基准接近闭源旗舰，并给出复现命令。",
        summary="短摘要一句。",
        category="大模型/LLM",
        score=3,
    )
    md = render_monthly_brief(kind=BriefKind.NEWS, year_month="2026-08", items=[item])
    assert "训练配方与评测脚本" in md
    assert "发生了什么" in md


def test_news_body_keeps_full_long_content_without_editorial_cap() -> None:
    """Weekly/monthly briefs must not clip news bodies for 'length budget'."""
    long = ("段落" + "具体事实与机制说明。" * 80) * 5  # well above old 1200 cap
    assert len(long) > 2000
    item = _item(content=long, summary="短摘要。", llm_summary="")
    body = _body_text(item)
    assert body == long
    assert not body.endswith("…")


def test_av_template_sections() -> None:
    md = render_monthly_brief(kind=BriefKind.AV, year_month="2026-08", items=[])
    assert "讲解口径（音视频）" in md
    assert "精选音视频" in md
