"""LLM-backed period brief generation from custom user prompts + item pool."""

from __future__ import annotations

import re
from typing import Sequence

from bagel.domain.models import IntelItem
from bagel.services.llm import LlmClient
from bagel.services.monthly_templates import _body_text, _display_title, _pick_top, _prioritize_by_prompt
from bagel.settings import Settings, get_settings

_POOL_PLACEHOLDERS = (
    "{{新闻池}}",
    "{{条目池}}",
    "{{资料池}}",
    "{{素材池}}",
    "{{论文池}}",
    "{{项目池}}",
    "{{item_pool}}",
    "{{ITEMS}}",
    "{{POOL}}",
)

_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*(新闻池|条目池|资料池|素材池|论文池|项目池|item_pool|ITEMS|POOL)\s*\}\}",
    re.I,
)


def format_item_pool(
    items: Sequence[IntelItem],
    *,
    max_items: int = 12,
) -> str:
    """Build the evidence block injected into custom brief prompts."""
    if not items:
        return "（本周期暂无可用条目）"
    lines: list[str] = []
    for idx, item in enumerate(items[:max_items], start=1):
        title = _display_title(item)
        pub = item.published_at.strftime("%Y-%m-%d") if item.published_at else "时间未知"
        cat = item.category or "其他"
        body = _body_text(item) or "（无正文）"
        lines.extend(
            [
                f"### [{idx}] {title}",
                f"- 日期：{pub}",
                f"- 主题：{cat}",
                f"- 链接：{item.url or '（无）'}",
                "",
                body,
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def inject_item_pool(prompt: str, pool: str) -> str:
    """Replace known pool placeholders; append pool if none present."""
    text = (prompt or "").strip()
    if not text:
        return f"## 素材池\n\n{pool}"
    if _PLACEHOLDER_RE.search(text):
        return _PLACEHOLDER_RE.sub(pool, text)
    for ph in _POOL_PLACEHOLDERS:
        if ph in text:
            return text.replace(ph, pool)
    return text.rstrip() + "\n\n## 素材池（系统自动注入）\n\n" + pool


def generate_llm_brief_markdown(
    *,
    kind: str,
    year_month: str,
    period_type: str,
    items: Sequence[IntelItem],
    user_prompt: str,
    system_prompt: str,
    settings: Settings | None = None,
    client: LlmClient | None = None,
) -> tuple[str | None, str | None]:
    """Call LLM with custom prompt + item pool. Returns (markdown, error)."""
    settings = settings or get_settings()
    llm = client or LlmClient(settings)
    if not llm.available:
        return None, "LLM 未配置或未启用（需 LLM_ENABLED / ENABLE_LLM_SUMMARY / BASE_URL / MODEL）"

    ordered = _prioritize_by_prompt(list(items), user_prompt)
    tops = _pick_top(ordered, 12)
    pool = format_item_pool(tops, max_items=12)
    user = inject_item_pool(user_prompt, pool)
    cadence = "周总结" if period_type == "week" else "月总结"
    system = (
        f"{system_prompt.strip()}\n\n"
        f"周期键：{year_month}（{cadence}）。"
        "只输出完整 Markdown 终稿，不要解释写作过程；不要用外层 ```markdown 包裹整篇。"
        "事实必须来自用户消息中的素材池，禁止编造链接或数字。"
    )
    return llm.complete_text(system=system, user=user, temperature=0.3)
