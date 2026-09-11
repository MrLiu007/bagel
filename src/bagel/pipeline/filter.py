"""Deterministic keyword filter — LLM must not auto-delete content."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from bagel.domain.enums import ItemStatus, KeywordRuleType
from bagel.domain.models import IntelKeywordRule

# Latin tokens: avoid "ai" matching inside "said"/"training", but allow "gpt" in "gpt-6".
_LATIN_TOKEN_RE_CACHE: dict[str, re.Pattern[str]] = {}


def keyword_matches(keyword: str, text_lower: str) -> bool:
    """Match keyword against haystack (case-insensitive).

    - CJK / mixed phrases: substring (titles rarely embed 大模型 inside unrelated words)
    - Latin tokens: alphanumeric-ish boundary so short tags stay precise;
      version suffixes allowed (`gpt-6`, `gpt6`)
    """
    kw = (keyword or "").strip().lower()
    hay = (text_lower or "").lower()
    if not kw or not hay:
        return False
    if any("\u4e00" <= ch <= "\u9fff" for ch in kw):
        return kw in hay
    # Multi-word / hyphenated Latin phrases: contiguous substring.
    if " " in kw or "-" in kw:
        return kw in hay
    pat = _LATIN_TOKEN_RE_CACHE.get(kw)
    if pat is None:
        # Allow version suffixes (gpt-6 / gpt6) but not embedding in longer words (said≠ai).
        pat = re.compile(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z])")
        _LATIN_TOKEN_RE_CACHE[kw] = pat
    return pat.search(hay) is not None


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
        if keyword_matches(rule.keyword, text):
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
        if keyword_matches(rule.keyword, text):
            matched_include.append(rule.keyword)
            score += float(rule.weight)

    for rule in boosts:
        if keyword_matches(rule.keyword, text):
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
