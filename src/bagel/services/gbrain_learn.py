"""GBrain flashcard learning — resource-first cards, focus paths, learn events.

Bagel is an intel hub (URLs + summaries), not a pure curriculum KB like Marble.
Cards prioritize: title → summary → open URL → related resources (with snippet+url).
Topics remain hubs that collect mounted resources for flashcard browsing.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType
from bagel.domain.models import GbrainLearnEvent, IntelItem
from bagel.pipeline.textutil import strip_html, truncate
from bagel.taxonomy import children_of, get_taxonomy

_TYPE_LABELS: dict[str, str] = {
    ItemType.NEWS: "新闻",
    ItemType.GITHUB_REPO: "GitHub",
    ItemType.GITHUB_RELEASE: "GitHub",
    ItemType.PAPER: "论文",
    ItemType.MODEL: "模型",
    ItemType.STOCK_NEWS: "股票",
    ItemType.EDUCATION: "教育",
    ItemType.MEDIA_POST: "自媒体",
    ItemType.WECHAT_MSG: "微信",
}


def _parse_key(key: str) -> tuple[str, str]:
    if ":" not in key:
        return "topic", key
    kind, rest = key.split(":", 1)
    return kind, rest


def record_learn(
    session: Session,
    *,
    node_key: str,
    action: str = "view",
    owner_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> GbrainLearnEvent:
    kind, _ = _parse_key(node_key)
    row = GbrainLearnEvent(
        owner_id=owner_id,
        node_key=node_key[:128],
        kind=kind[:32],
        action=(action or "view")[:32],
        metadata_=metadata or {},
    )
    session.add(row)
    session.flush()
    return row


def _item_summary(item: IntelItem, *, limit: int = 220) -> str:
    return truncate(
        strip_html(item.llm_summary or item.summary or item.content or ""),
        limit,
    )


def _resource_entry(item: IntelItem, *, summary_limit: int = 160) -> dict[str, Any]:
    title = strip_html(item.llm_title_zh or item.title)[:140]
    summary = _item_summary(item, limit=summary_limit) or "暂无摘要，可打开原文查看。"
    type_label = _TYPE_LABELS.get(item.item_type or "", item.item_type or "资源")
    return {
        "key": f"item:{item.id}",
        "id": str(item.id),
        "name": title,
        "title": title,
        "summary": summary,
        "url": item.url or "",
        "type": item.item_type,
        "type_label": type_label,
        "subject": type_label,
        "kind": "item",
    }


def _match_topic_items(session: Session, topic_id: str, *, limit: int = 12) -> list[IntelItem]:
    tax = get_taxonomy()
    topic = tax.get(topic_id)
    if topic is None:
        return []
    items = list(
        session.scalars(
            select(IntelItem)
            .where(IntelItem.status != ItemStatus.REJECTED)
            .order_by(IntelItem.published_at.desc().nullslast())
            .limit(300)
        ).all()
    )
    needles = {a.lower() for a in topic.aliases} | {topic.name.lower()}
    hit: list[IntelItem] = []
    for item in items:
        blob = f"{item.title} {item.summary or ''} {item.category or ''}".lower()
        ok = any(n and n in blob for n in needles)
        if topic.category and item.category == topic.category:
            ok = True
        if ok:
            hit.append(item)
        if len(hit) >= limit:
            break
    return hit


def _topic_card(session: Session, topic_id: str) -> dict[str, Any] | None:
    tax = get_taxonomy()
    topic = tax.get(topic_id)
    if topic is None:
        return None

    builds = []
    unlocks = []
    for dep in tax.dependencies:
        if dep.topic_id == topic_id:
            pr = tax.get(dep.prerequisite_id)
            if pr:
                builds.append(
                    {
                        "key": f"topic:{pr.id}",
                        "id": pr.id,
                        "name": pr.name,
                        "title": pr.name,
                        "summary": truncate(pr.description, 120),
                        "url": "",
                        "subject": pr.subject,
                        "type_label": "主题",
                        "kind": "topic",
                        "strength": dep.strength,
                        "reason": dep.reason,
                    }
                )
        if dep.prerequisite_id == topic_id:
            ch = tax.get(dep.topic_id)
            if ch:
                unlocks.append(
                    {
                        "key": f"topic:{ch.id}",
                        "id": ch.id,
                        "name": ch.name,
                        "title": ch.name,
                        "summary": truncate(ch.description, 120),
                        "url": "",
                        "subject": ch.subject,
                        "type_label": "主题",
                        "kind": "topic",
                        "strength": dep.strength,
                        "reason": dep.reason,
                    }
                )

    seen: set[str] = set()
    stack = [b["id"] for b in builds]
    while stack:
        tid = stack.pop()
        if tid in seen:
            continue
        seen.add(tid)
        for dep in tax.dependencies:
            if dep.topic_id == tid and dep.prerequisite_id not in seen:
                stack.append(dep.prerequisite_id)

    kids = [
        {
            "key": f"topic:{c.id}",
            "id": c.id,
            "name": c.name,
            "title": c.name,
            "summary": truncate(c.description, 120),
            "url": "",
            "subject": c.subject,
            "type_label": "子主题",
            "kind": "topic",
        }
        for c in children_of(tax, topic_id)
    ]

    parent = tax.get(topic.parent_id) if topic.parent_id else None
    linked = _match_topic_items(session, topic_id, limit=12)
    resources = [_resource_entry(i) for i in linked]

    summary_bits = [
        topic.description,
        f"挂载资源 {len(resources)} 条；直接先修 {len(builds)} · 可解锁 {len(unlocks)}"
        + (f" · 子主题 {len(kids)}" if kids else "")
        + "。点击下方资源可看摘要并打开原文。",
    ]

    return {
        "key": f"topic:{topic.id}",
        "kind": "topic",
        "id": topic.id,
        "title": topic.name,
        "subtitle": f"主题枢纽 · {topic.subject}"
        + (f" / {topic.domain}" if topic.domain else ""),
        "description": topic.description,
        "evidence": list(topic.evidence),
        "summary": "\n".join(summary_bits),
        "prereq_total": len(seen),
        "resource_count": len(resources),
        "builds_on": builds,
        "unlocks": unlocks,
        "subtopics": kids,
        "parent": (
            {"key": f"topic:{parent.id}", "id": parent.id, "name": parent.name}
            if parent
            else None
        ),
        "resources": resources,
        "related_resources": resources,
        "url": "",
        "primary_cta": "browse_resources",
        "focus_keys": [f"topic:{topic.id}"]
        + [b["key"] for b in builds]
        + [u["key"] for u in unlocks]
        + [k["key"] for k in kids]
        + [r["key"] for r in resources[:8]],
    }


def _related_resources(session: Session, seed: IntelItem, *, limit: int = 8) -> list[dict[str, Any]]:
    from bagel.services.wiki_compile import topics_for_item

    topics = topics_for_item(seed)
    if not topics:
        return []
    seen: set[str] = {str(seed.id)}
    out: list[dict[str, Any]] = []
    for t in topics[:3]:
        for item in _match_topic_items(session, t.id, limit=10):
            iid = str(item.id)
            if iid in seen:
                continue
            seen.add(iid)
            out.append(_resource_entry(item))
            if len(out) >= limit:
                return out
    return out


def _item_card(session: Session, item_id: str) -> dict[str, Any] | None:
    try:
        uid = UUID(item_id)
    except ValueError:
        return None
    item = session.get(IntelItem, uid)
    if item is None:
        return None
    from bagel.services.wiki_compile import topics_for_item

    topics = topics_for_item(item)
    body = _item_summary(item, limit=700)
    type_label = _TYPE_LABELS.get(item.item_type or "", item.item_type or "资源")
    related_topics = [
        {
            "key": f"topic:{t.id}",
            "id": t.id,
            "name": t.name,
            "title": t.name,
            "summary": truncate(t.description, 120),
            "url": "",
            "subject": t.subject,
            "type_label": "主题",
            "kind": "topic",
        }
        for t in topics
    ]
    related = _related_resources(session, item, limit=8)
    return {
        "key": f"item:{item.id}",
        "kind": "item",
        "id": str(item.id),
        "title": strip_html(item.llm_title_zh or item.title)[:200],
        "subtitle": f"资源 · {type_label}"
        + (f" · {item.category}" if item.category else ""),
        "description": body or "该资源尚无摘要，请打开原文阅读。",
        "evidence": [],
        "summary": body or "该资源尚无摘要，请打开原文阅读。",
        "prereq_total": 0,
        "resource_count": 1,
        "builds_on": related_topics,
        "unlocks": [],
        "subtopics": [],
        "parent": None,
        "resources": [],
        "related_resources": related,
        "url": item.url or "",
        "type_label": type_label,
        "primary_cta": "open_url",
        "focus_keys": [f"item:{item.id}"]
        + [t["key"] for t in related_topics]
        + [r["key"] for r in related[:5]],
    }


def _cluster_card(session: Session, cluster_id: str) -> dict[str, Any] | None:
    tax = get_taxonomy()
    cluster = tax.clusters.get(cluster_id)
    if cluster is None:
        return None
    members = []
    resources: list[dict[str, Any]] = []
    for tid in cluster.topic_ids:
        t = tax.get(tid)
        if t:
            members.append(
                {
                    "key": f"topic:{t.id}",
                    "id": t.id,
                    "name": t.name,
                    "title": t.name,
                    "summary": truncate(t.description, 120),
                    "url": "",
                    "subject": t.subject,
                    "type_label": "主题",
                    "kind": "topic",
                }
            )
            for item in _match_topic_items(session, tid, limit=3):
                entry = _resource_entry(item)
                if entry["key"] not in {r["key"] for r in resources}:
                    resources.append(entry)
                if len(resources) >= 10:
                    break
    return {
        "key": f"cluster:{cluster.id}",
        "kind": "cluster",
        "id": cluster.id,
        "title": cluster.name,
        "subtitle": f"主题簇 · {cluster.subject} · {cluster.domain}",
        "description": cluster.summary,
        "evidence": [],
        "summary": cluster.summary + f"\n本簇 {len(members)} 个主题，示例资源 {len(resources)} 条。",
        "prereq_total": 0,
        "resource_count": len(resources),
        "builds_on": [],
        "unlocks": members,
        "subtopics": members,
        "parent": None,
        "resources": resources,
        "related_resources": resources,
        "url": "",
        "primary_cta": "browse_resources",
        "focus_keys": [f"cluster:{cluster.id}"]
        + [m["key"] for m in members]
        + [r["key"] for r in resources[:6]],
    }


def knowledge_card(session: Session, node_key: str) -> dict[str, Any] | None:
    kind, rest = _parse_key(node_key)
    if kind == "topic":
        return _topic_card(session, rest)
    if kind == "item":
        return _item_card(session, rest)
    if kind == "cluster":
        return _cluster_card(session, rest)
    return {
        "key": node_key,
        "kind": kind,
        "id": rest,
        "title": rest,
        "subtitle": f"枢纽 · {kind}",
        "description": f"「{rest}」是图谱枢纽。用左侧 SUBJECTS 筛选资源频道，点击红色资源点查看摘要与原文。",
        "evidence": [],
        "summary": f"「{rest}」是图谱枢纽。用左侧 SUBJECTS 筛选资源频道，点击红色资源点查看摘要与原文。",
        "prereq_total": 0,
        "resource_count": 0,
        "builds_on": [],
        "unlocks": [],
        "subtopics": [],
        "parent": None,
        "resources": [],
        "related_resources": [],
        "url": "",
        "primary_cta": "browse_resources",
        "focus_keys": [node_key],
    }


def review_summary(
    session: Session,
    *,
    owner_id: UUID | None = None,
    days: int = 14,
    limit: int = 20,
) -> dict[str, Any]:
    """Learning analytics: recent views + resource/topic review suggestions."""
    since = datetime.now(UTC) - timedelta(days=days)
    q = select(GbrainLearnEvent).where(GbrainLearnEvent.created_at >= since)
    if owner_id is not None:
        q = q.where(GbrainLearnEvent.owner_id == owner_id)
    rows = list(session.scalars(q.order_by(GbrainLearnEvent.created_at.desc()).limit(500)).all())
    counts: Counter[str] = Counter(r.node_key for r in rows if r.action in {"view", "focus"})
    marked = {r.node_key for r in rows if r.action == "review"}
    recent = []
    seen: set[str] = set()
    for r in rows:
        if r.node_key in seen:
            continue
        seen.add(r.node_key)
        recent.append(
            {
                "key": r.node_key,
                "kind": r.kind,
                "action": r.action,
                "at": r.created_at.isoformat() if r.created_at else "",
                "views": counts.get(r.node_key, 1),
            }
        )
        if len(recent) >= limit:
            break

    suggestions = []
    for key, n in counts.most_common(50):
        if key in marked:
            continue
        card = knowledge_card(session, key)
        if not card:
            continue
        why = (
            "近期看过该资源但未标记复习，建议再读摘要或打开原文"
            if key.startswith("item:")
            else "近期浏览主题枢纽，建议沿资源摘要继续闪卡"
        )
        suggestions.append(
            {
                "key": key,
                "title": card["title"],
                "subtitle": card.get("subtitle") or "",
                "views": n,
                "prereq_total": card.get("prereq_total") or 0,
                "url": card.get("url") or "",
                "why": why,
            }
        )
        if len(suggestions) >= 8:
            break

    return {
        "days": days,
        "event_count": len(rows),
        "unique_nodes": len(counts),
        "recent": recent,
        "hot": [{"key": k, "views": v} for k, v in counts.most_common(10)],
        "suggestions": suggestions,
    }
