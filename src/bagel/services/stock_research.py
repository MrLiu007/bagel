"""Lightweight multi-perspective stock research draft (LLM, evidence-bound)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from bagel.domain.models import IntelItem
from bagel.services import stock_events
from bagel.services.llm import LlmClient, _parse_json_object
from bagel.services.prompts import (
    STOCK_RESEARCH_PROMPT_VERSION,
    STOCK_RESEARCH_SYSTEM,
    STOCK_RESEARCH_USER_TEMPLATE,
)
from bagel.settings import get_settings


@dataclass
class ResearchDraft:
    symbol: str
    markdown: str
    perspectives: dict[str, str]
    risks: list[str]
    evidence_ids: list[str]
    prompt_version: str = STOCK_RESEARCH_PROMPT_VERSION
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.markdown)


def build_research_draft(
    session: Session,
    *,
    symbol: str,
    owner_id: UUID | None = None,
    days: int = 14,
) -> ResearchDraft:
    settings = get_settings()
    sym = (symbol or "").strip().upper()
    if not settings.enable_stock_research_draft:
        return ResearchDraft(
            symbol=sym,
            markdown="",
            perspectives={},
            risks=[],
            evidence_ids=[],
            error="research draft disabled",
        )

    items = stock_events.list_stock_items(session, owner_id=owner_id, days=days, limit=400)
    bundle = stock_events.get_symbol_bundle(items, sym)
    if bundle is None or not bundle.items:
        return ResearchDraft(
            symbol=sym,
            markdown=_fallback_markdown(sym, []),
            perspectives={},
            risks=["暂无足够关联资讯，无法形成证据链。"],
            evidence_ids=[],
            error=None,
        )

    evidence = bundle.items[:12]
    evidence_block = _format_evidence(evidence)
    client = LlmClient(settings)
    if not client.available:
        return ResearchDraft(
            symbol=sym,
            markdown=_fallback_markdown(sym, evidence),
            perspectives={
                "bull": "（LLM 未配置）根据标题偏多线索见证据列表。",
                "bear": "（LLM 未配置）根据标题偏空线索见证据列表。",
                "neutral": "仅作资讯整理，不构成投资建议。",
            },
            risks=["公开资讯可能滞后或不完整", "情绪标签为关键词启发式，可能误判"],
            evidence_ids=[str(i.id) for i in evidence],
        )

    user = STOCK_RESEARCH_USER_TEMPLATE.format(
        symbol=sym,
        name=bundle.name,
        evidence=evidence_block,
    )
    raw = _chat_json(client, STOCK_RESEARCH_SYSTEM, user)
    if raw is None:
        return ResearchDraft(
            symbol=sym,
            markdown=_fallback_markdown(sym, evidence),
            perspectives={},
            risks=["LLM 解析失败，已回退到证据列表。"],
            evidence_ids=[str(i.id) for i in evidence],
        )

    perspectives = {
        "bull": str(raw.get("bull") or raw.get("bullish") or "")[:800],
        "bear": str(raw.get("bear") or raw.get("bearish") or "")[:800],
        "neutral": str(raw.get("neutral") or raw.get("synthesis") or "")[:800],
    }
    risks = [str(r)[:200] for r in (raw.get("risks") or []) if str(r).strip()][:8]
    md = str(raw.get("markdown") or "").strip()
    if not md:
        md = _compose_markdown(sym, bundle.name, perspectives, risks, evidence)
    disclaimer = (
        "\n\n---\n\n> **免责声明**：本草稿仅基于站内已采集公开资讯整理，"
        "供学习与讨论，**不构成投资建议**，不保证完整或及时。\n"
    )
    if "免责声明" not in md:
        md = md + disclaimer
    return ResearchDraft(
        symbol=sym,
        markdown=md,
        perspectives=perspectives,
        risks=risks,
        evidence_ids=[str(i.id) for i in evidence],
    )


def _chat_json(client: LlmClient, system: str, user: str) -> dict[str, Any] | None:
    import httpx

    from bagel.integrations.http import build_http_client

    payload = {
        "model": client.settings.llm_model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    if client.settings.llm_api_key:
        headers["Authorization"] = f"Bearer {client.settings.llm_api_key}"
    url = client.settings.llm_base_url.rstrip("/") + "/chat/completions"
    timeout = float(getattr(client.settings, "llm_timeout_seconds", 180) or 180)
    try:
        with build_http_client(client.settings, timeout=timeout) as http:
            resp = http.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        )
        return _parse_json_object(content)
    except (httpx.HTTPError, OSError, ValueError):
        return None


def _format_evidence(items: list[IntelItem]) -> str:
    lines: list[str] = []
    for i, item in enumerate(items, start=1):
        meta = stock_events.stock_meta(item)
        sent = meta.get("sentiment") or "neutral"
        themes = ", ".join(meta.get("themes") or []) or "-"
        body = (item.summary or item.llm_summary or "")[:280]
        lines.append(
            f"{i}. id={item.id}\n"
            f"   title: {item.title}\n"
            f"   url: {item.url}\n"
            f"   published: {item.published_at}\n"
            f"   sentiment: {sent}; themes: {themes}\n"
            f"   summary: {body}"
        )
    return "\n".join(lines)


def _compose_markdown(
    symbol: str,
    name: str,
    perspectives: dict[str, str],
    risks: list[str],
    evidence: list[IntelItem],
) -> str:
    lines = [
        f"# {symbol}（{name}）研读草稿",
        "",
        "## 看多视角",
        "",
        perspectives.get("bull") or "（暂无）",
        "",
        "## 看空视角",
        "",
        perspectives.get("bear") or "（暂无）",
        "",
        "## 中性综合",
        "",
        perspectives.get("neutral") or "（暂无）",
        "",
        "## 风险与不确定点",
        "",
    ]
    if risks:
        lines.extend(f"- {r}" for r in risks)
    else:
        lines.append("- （暂无）")
    lines.extend(["", "## 证据链", ""])
    for item in evidence:
        lines.append(f"- [{item.title}]({item.url})")
    return "\n".join(lines)


def _fallback_markdown(symbol: str, evidence: list[IntelItem]) -> str:
    lines = [
        f"# {symbol} 研读草稿（规则回退）",
        "",
        "LLM 未启用或证据不足时，仅列出关联资讯。**不构成投资建议。**",
        "",
        "## 证据链",
        "",
    ]
    if not evidence:
        lines.append("- （暂无）")
    else:
        for item in evidence:
            lines.append(f"- [{item.title}]({item.url})")
    lines.append(
        "\n---\n\n> **免责声明**：公开资讯整理，仅供学习讨论，不构成投资建议。\n"
    )
    return "\n".join(lines)
