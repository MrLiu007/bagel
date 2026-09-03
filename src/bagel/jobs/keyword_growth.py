"""Scheduled job: expand interest tags / exclude words from search analytics."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, KeywordRuleType
from bagel.domain.models import IntelItem, IntelKeywordRule
from bagel.pipeline.keyword_scopes import ALL_SCOPES
from bagel.services import search_analytics
from bagel.services import settings_svc

_SPAM_PATTERNS = re.compile(
    r"(培训招生|荐股|付费课程|娱乐八卦|加微信|免费领取|私信领取|限时优惠|"
    r"报名热线|代理招募|刷单|网赚|博彩|色情|吃瓜)",
    re.I,
)

_TYPE_TO_SCOPE: dict[str, str] = {
    ItemType.NEWS: "news",
    ItemType.GITHUB_REPO: "github",
    ItemType.GITHUB_RELEASE: "github",
    ItemType.STOCK_NEWS: "stocks",
    ItemType.PAPER: "papers",
    ItemType.EDUCATION: "education",
    ItemType.MODEL: "models",
    ItemType.MEDIA_POST: "media",
    ItemType.WECHAT_MSG: "wechat",
}


def _scope_for_types(types: list[str]) -> str:
    for t in types:
        if t in _TYPE_TO_SCOPE:
            return _TYPE_TO_SCOPE[t]
    return "news"


def run_expand_keywords_from_search(session: Session) -> dict[str, Any]:
    """Idempotent: upsert INCLUDE/EXCLUDE from frequent search queries."""
    rows = search_analytics.aggregate_search_keywords(session, min_count=2, days=30)
    include_added = 0
    exclude_added = 0
    skipped = 0

    for row in rows:
        query = (row.get("query") or "").strip()
        if not query or len(query) < 2:
            skipped += 1
            continue
        if _SPAM_PATTERNS.search(query):
            try:
                settings_svc.add_exclude_tag(session, query, scopes=list(ALL_SCOPES))
                exclude_added += 1
            except settings_svc.SettingsError:
                skipped += 1
            continue
        scope = _scope_for_types(row.get("item_types") or [])
        if scope not in {"news", "github", "stocks", "papers", "models", "education"}:
            skipped += 1
            continue
        try:
            settings_svc.add_filter_tag(session, query, scope=scope)
            include_added += 1
        except settings_svc.SettingsError:
            skipped += 1

    existing_exclude = {
        r.keyword.lower()
        for r in session.scalars(
            select(IntelKeywordRule).where(
                IntelKeywordRule.rule_type == KeywordRuleType.EXCLUDE
            )
        ).all()
    }
    rejected = session.scalars(
        select(IntelItem.title)
        .where(IntelItem.status == ItemStatus.REJECTED)
        .limit(200)
    ).all()
    for title in rejected:
        if not title or not _SPAM_PATTERNS.search(title):
            continue
        for m in _SPAM_PATTERNS.finditer(title):
            token = m.group(0)
            if token.lower() in existing_exclude:
                continue
            try:
                settings_svc.add_exclude_tag(session, token, scopes=list(ALL_SCOPES))
                existing_exclude.add(token.lower())
                exclude_added += 1
            except settings_svc.SettingsError:
                pass

    return {
        "status": "SUCCESS",
        "include_added": include_added,
        "exclude_added": exclude_added,
        "skipped": skipped,
        "candidates": len(rows),
    }
