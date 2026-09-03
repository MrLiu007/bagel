"""Ingest Gewe WeChat webhook messages into IntelItem rows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType, KeywordScope, SourceType
from bagel.integrations.gewe import extract_message, keyword_hit
from bagel.pipeline.category import classify_title
from bagel.pipeline.filter import apply_keyword_rules
from bagel.pipeline.keyword_scopes import rules_for_scope
from bagel.settings import get_settings
from bagel.storage.repositories import ItemRepository, KeywordRuleRepository
from bagel.services import wiki as wiki_svc


def ingest_wechat_payload(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.wechat_active:
        return {"accepted": False, "reason": "wechat_disabled"}

    msg = extract_message(payload)
    if msg is None:
        return {"accepted": False, "reason": "empty"}

    content = msg["content"]
    if not keyword_hit(content, settings=settings):
        return {"accepted": False, "reason": "no_keyword"}

    msg_id = msg.get("msg_id") or content[:40]
    url = f"wechat://gewe/{msg_id}"
    title = content[:80].replace("\n", " ")
    rules = rules_for_scope(
        KeywordRuleRepository(session).list_enabled(),
        KeywordScope.WECHAT,
    )
    filt = apply_keyword_rules(title, content, rules)
    status = filt.status if filt.accepted else ItemStatus.REJECTED
    repo = ItemRepository(session)
    item, created = repo.upsert_from_normalized(
        item_type=ItemType.WECHAT_MSG,
        source_type=SourceType.WECHAT,
        source_id=None,
        title=title,
        url=url,
        summary=content[:2000],
        content=content,
        author=msg.get("from_user") or None,
        published_at=datetime.now(UTC),
        tags=["wechat", *settings.gewe_keyword_list][:12],
        category=classify_title(title, content),
        metadata={
            "gewe": msg.get("raw") or {},
            "filter": {
                "include": filt.matched_include,
                "exclude": filt.matched_exclude,
                "boost": filt.matched_boost,
            },
        },
        status=status,
        score=1.2 + filt.score,
    )
    if created:
        wiki_svc.export_item(item, settings)
    return {"accepted": True, "created": created, "item_id": str(item.id)}
