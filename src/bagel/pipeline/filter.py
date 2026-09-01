"""Deterministic keyword filter — LLM must not auto-delete content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from bagel.domain.enums import KeywordRuleType, ItemStatus
from bagel.domain.models import IntelKeywordRule


@dataclass
class FilterResult:
    accepted: bool
    score: float
    matched_include: list[str]
    matched_exclude: list[str]
    matched_boost: list[str]
    status: str


def apply_keyword_rules(
    title: str,
    summary: str | None,
    rules: Sequence[IntelKeywordRule],
    *,
    base_score: float = 0.0,
) -> FilterResult:
    text = f"{title}\n{summary or ''}".lower()
    matched_include: list[str] = []
    matched_exclude: list[str] = []
    matched_boost: list[str] = []
    score = base_score

    def _on(rule: IntelKeywordRule) -> bool:
        # SQLAlchemy column default applies on flush; treat unset as enabled.
        return rule.enabled is not False

    includes = [r for r in rules if r.rule_type == KeywordRuleType.INCLUDE and _on(r)]
    excludes = [r for r in rules if r.rule_type == KeywordRuleType.EXCLUDE and _on(r)]
    boosts = [r for r in rules if r.rule_type == KeywordRuleType.BOOST and _on(r)]

    for rule in excludes:
        if rule.keyword.lower() in text:
            matched_exclude.append(rule.keyword)

    if matched_exclude:
        return FilterResult(
            accepted=False,
            score=score,
            matched_include=matched_include,
            matched_exclude=matched_exclude,
            matched_boost=matched_boost,
            status=ItemStatus.REJECTED,
        )

    for rule in includes:
        if rule.keyword.lower() in text:
            matched_include.append(rule.keyword)
            score += float(rule.weight)

    for rule in boosts:
        if rule.keyword.lower() in text:
            matched_boost.append(rule.keyword)
            score += float(rule.weight)

    # If INCLUDE rules exist, require at least one match; otherwise accept all non-excluded.
    if includes and not matched_include:
        return FilterResult(
            accepted=False,
            score=score,
            matched_include=matched_include,
            matched_exclude=matched_exclude,
            matched_boost=matched_boost,
            status=ItemStatus.REJECTED,
        )

    return FilterResult(
        accepted=True,
        score=score,
        matched_include=matched_include,
        matched_exclude=matched_exclude,
        matched_boost=matched_boost,
        status=ItemStatus.CANDIDATE,
    )
