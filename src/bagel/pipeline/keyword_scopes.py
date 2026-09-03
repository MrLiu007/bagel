"""Keyword rule scopes — which resource categories a rule applies to."""

from __future__ import annotations

from typing import Sequence

from bagel.domain.enums import KeywordRuleType, KeywordScope
from bagel.domain.models import IntelKeywordRule

ALL_SCOPES: tuple[str, ...] = tuple(s.value for s in KeywordScope)

# Interest tags (INCLUDE) UI / gating — media & wechat use env keywords instead.
INCLUDE_SCOPES: tuple[str, ...] = (
    KeywordScope.NEWS,
    KeywordScope.GITHUB,
    KeywordScope.STOCKS,
    KeywordScope.PAPERS,
    KeywordScope.MODELS,
    KeywordScope.EDUCATION,
)

SCOPE_LABELS: dict[str, str] = {
    KeywordScope.NEWS: "新闻",
    KeywordScope.GITHUB: "GitHub",
    KeywordScope.STOCKS: "股票",
    KeywordScope.PAPERS: "论文",
    KeywordScope.MODELS: "模型",
    KeywordScope.EDUCATION: "教育",
    KeywordScope.MEDIA: "自媒体",
    KeywordScope.WECHAT: "微信",
}

TAB_TO_SCOPE: dict[str, str] = {
    "sources": KeywordScope.NEWS,
    "github": KeywordScope.GITHUB,
    "stocks": KeywordScope.STOCKS,
    "papers": KeywordScope.PAPERS,
    "models": KeywordScope.MODELS,
    "education": KeywordScope.EDUCATION,
}

SCOPE_TO_TAB: dict[str, str] = {v: k for k, v in TAB_TO_SCOPE.items()}


def parse_scopes(raw: str | None) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    out: list[str] = []
    for part in str(raw).split(","):
        key = part.strip().lower()
        if key in ALL_SCOPES and key not in out:
            out.append(key)
    return out


def serialize_scopes(scopes: Sequence[str]) -> str:
    seen: list[str] = []
    for s in scopes:
        key = str(s).strip().lower()
        if key in ALL_SCOPES and key not in seen:
            seen.append(key)
    return ",".join(seen)


def effective_scopes(rule: IntelKeywordRule) -> list[str]:
    """Resolve scopes with legacy empty-column defaults."""
    parsed = parse_scopes(getattr(rule, "scopes", None))
    if parsed:
        return parsed
    if rule.rule_type == KeywordRuleType.INCLUDE:
        return [KeywordScope.NEWS]
    # EXCLUDE / BOOST historically applied to news + github + stocks; expand EXCLUDE to all.
    if rule.rule_type == KeywordRuleType.EXCLUDE:
        return list(ALL_SCOPES)
    return list(INCLUDE_SCOPES)


def rule_applies_to(rule: IntelKeywordRule, scope: str) -> bool:
    return scope in effective_scopes(rule)


def rules_for_scope(
    rules: Sequence[IntelKeywordRule],
    scope: str,
    *,
    enabled_only: bool = True,
) -> list[IntelKeywordRule]:
    out: list[IntelKeywordRule] = []
    for rule in rules:
        if enabled_only and rule.enabled is False:
            continue
        if rule_applies_to(rule, scope):
            out.append(rule)
    return out
