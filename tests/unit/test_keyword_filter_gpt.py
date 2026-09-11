"""Keyword filter matching — GPT-6 must pass INCLUDE GPT."""

from __future__ import annotations

from bagel.domain.enums import ItemStatus, KeywordRuleType
from bagel.domain.models import IntelKeywordRule
from bagel.pipeline.filter import apply_keyword_rules, keyword_matches


def test_keyword_matches_gpt_variant() -> None:
    assert keyword_matches("GPT", "openai announces gpt-6 today")
    assert keyword_matches("gpt", "GPT6 preview")
    assert not keyword_matches("ai", "available training said")  # no bare substring trap
    assert keyword_matches("大模型", "新一代大模型发布")


def test_include_accepts_gpt6_with_gpt_tag() -> None:
    rules = [
        IntelKeywordRule(keyword="LLM", rule_type=KeywordRuleType.INCLUDE, weight=2.0, enabled=True),
        IntelKeywordRule(keyword="GPT", rule_type=KeywordRuleType.INCLUDE, weight=2.5, enabled=True),
        IntelKeywordRule(keyword="开源", rule_type=KeywordRuleType.BOOST, weight=1.2, enabled=True),
    ]
    hit = apply_keyword_rules("OpenAI announces GPT-6", None, rules)
    assert hit.accepted is True
    assert "GPT" in hit.matched_include
    assert hit.status == ItemStatus.CANDIDATE

    miss = apply_keyword_rules(
        "OpenAI announces GPT-6",
        None,
        [IntelKeywordRule(keyword="LLM", rule_type=KeywordRuleType.INCLUDE, weight=2.0, enabled=True)],
    )
    assert miss.accepted is False


def test_ensure_default_interest_keywords_adds_gpt(tmp_path) -> None:
    from sqlalchemy import select

    from bagel.domain.models import Base
    from bagel.storage.database import get_engine, get_session_factory
    from bagel.storage.seed import ensure_default_interest_keywords

    engine = get_engine(f"sqlite+pysqlite:///{tmp_path / 'kw.db'}")
    Base.metadata.create_all(engine)
    session = get_session_factory(engine)()
    session.add(
        IntelKeywordRule(
            keyword="开源",
            rule_type=KeywordRuleType.INCLUDE,
            weight=1.5,
            enabled=True,
            scopes="news",
        )
    )
    session.commit()
    n = ensure_default_interest_keywords(session)
    session.commit()
    assert n >= 1
    rows = list(session.scalars(select(IntelKeywordRule)).all())
    by = {(r.keyword, r.rule_type): r for r in rows}
    assert ("GPT", KeywordRuleType.INCLUDE) in by
    assert ("开源", KeywordRuleType.INCLUDE) not in by
    assert ("开源", KeywordRuleType.BOOST) in by
    assert "news" in (by[("GPT", KeywordRuleType.INCLUDE)].scopes or "")
    session.close()
    engine.dispose()
