"""Scoped keyword rules: INCLUDE per category, EXCLUDE multi-scope."""

from __future__ import annotations

from bagel.domain.enums import KeywordRuleType, KeywordScope
from bagel.domain.models import IntelKeywordRule
from bagel.pipeline.filter import apply_keyword_rules
from bagel.pipeline.keyword_scopes import effective_scopes, rules_for_scope, serialize_scopes


def test_include_gates_only_matching_scope() -> None:
    rules = [
        IntelKeywordRule(
            keyword="LLM",
            rule_type=KeywordRuleType.INCLUDE,
            weight=2.0,
            enabled=True,
            scopes="news",
        ),
        IntelKeywordRule(
            keyword="荐股",
            rule_type=KeywordRuleType.EXCLUDE,
            weight=0.0,
            enabled=True,
            scopes=serialize_scopes(list(KeywordScope)),
        ),
    ]
    news_rules = rules_for_scope(rules, KeywordScope.NEWS)
    github_rules = rules_for_scope(rules, KeywordScope.GITHUB)

    assert apply_keyword_rules("Random sports", None, news_rules).accepted is False
    # GitHub has no INCLUDE in scope → no interest gate; only EXCLUDE applies.
    assert apply_keyword_rules("Random sports", None, github_rules).accepted is True
    assert apply_keyword_rules("今日荐股精选", None, github_rules).accepted is False


def test_exclude_scope_subset() -> None:
    rules = [
        IntelKeywordRule(
            keyword="付费课程",
            rule_type=KeywordRuleType.EXCLUDE,
            weight=0.0,
            enabled=True,
            scopes="media,wechat",
        )
    ]
    assert apply_keyword_rules("付费课程广告", None, rules_for_scope(rules, "media")).accepted is False
    assert apply_keyword_rules("付费课程广告", None, rules_for_scope(rules, "news")).accepted is True


def test_legacy_empty_scopes_defaults() -> None:
    include = IntelKeywordRule(
        keyword="Agent",
        rule_type=KeywordRuleType.INCLUDE,
        weight=1.0,
        enabled=True,
        scopes="",
    )
    exclude = IntelKeywordRule(
        keyword="荐股",
        rule_type=KeywordRuleType.EXCLUDE,
        weight=0.0,
        enabled=True,
        scopes="",
    )
    assert effective_scopes(include) == [KeywordScope.NEWS]
    assert KeywordScope.WECHAT in effective_scopes(exclude)
    assert KeywordScope.MODELS in effective_scopes(exclude)
