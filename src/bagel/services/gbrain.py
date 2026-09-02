"""GBrain — knowledge graph via WikiItem adapter + ECharts-ready payload.

Heterogeneous IntelItem types (news / papers / stocks / models / education / …)
are adapted into a unified WikiItem protocol before graph construction.
No external graph / vector DB.

Product goal: enough clickable *resource* nodes (items with original URLs) for
learning / research, plus concept hubs that deep-link into in-app browse/filter.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Sequence
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType
from bagel.domain.models import IntelItem, IntelSource
from bagel.pipeline.textutil import strip_html, truncate

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

_LIST_PATHS: dict[str, str] = {
    ItemType.NEWS: "/news",
    ItemType.GITHUB_REPO: "/github",
    ItemType.GITHUB_RELEASE: "/github",
    ItemType.PAPER: "/papers",
    ItemType.MODEL: "/models",
    ItemType.STOCK_NEWS: "/stocks",
    ItemType.EDUCATION: "/education",
    ItemType.MEDIA_POST: "/media",
    ItemType.WECHAT_MSG: "/wechat",
}

_KIND_COLORS: dict[str, str] = {
    "type": "#3b82f6",
    "category": "#8b5cf6",
    "tag": "#14b8a6",
    "source": "#f59e0b",
    "item": "#ef4444",
    "institution": "#22c55e",
}

_KIND_LABELS_ZH: dict[str, str] = {
    "type": "类型",
    "category": "分类",
    "tag": "标签",
    "source": "数据源",
    "item": "资源",
    "institution": "院校",
}


@dataclass
class WikiItem:
    """Unified resource protocol for GBrain (adapter target)."""

    id: str
    title: str
    text_content: str
    tags: list[str]
    file_url: str
    item_type: str
    type_label: str
    category: str = ""
    source_name: str = ""
    folder_path: str = ""
    list_path: str = "/news"


@dataclass
class GraphNode:
    id: str
    label: str
    kind: str
    weight: int = 0
    url: str = ""
    category: str = ""
    hint: str = ""


@dataclass
class GraphEdge:
    source: str
    target: str
    weight: int
    relation: str = "co_occur"


@dataclass
class KnowledgeGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    top_links: list[dict[str, Any]] = field(default_factory=list)
    echarts: dict[str, Any] = field(default_factory=dict)


def _node_id(kind: str, label: str) -> str:
    return f"{kind}:{label}"


def _browse_url(*, kind: str, label: str, list_path: str) -> str:
    """In-app deep link for concept nodes (分类 / 标签 / 类型 …)."""
    path = list_path or "/news"
    q = quote(label, safe="")
    if kind == "category":
        return f"{path}?category={q}"
    if kind == "tag":
        return f"/briefs/space?q={q}"
    if kind == "source":
        return path
    if kind == "type":
        return path
    if kind == "institution":
        return "/education"
    return ""


def adapt_intel_item(item: IntelItem, *, source_name: str = "") -> WikiItem:
    """Map heterogeneous IntelItem → WikiItem (adapter layer)."""
    itype = item.item_type or ItemType.NEWS
    type_label = _TYPE_LABELS.get(itype, itype)
    title = strip_html(item.llm_title_zh or item.title) or item.title or ""
    body = strip_html(item.summary or item.content or item.llm_summary or "")
    tags = [str(t) for t in (item.tags or []) if t][:12]
    meta = item.metadata_ or {}
    list_path = _LIST_PATHS.get(itype, "/news")

    if itype == ItemType.NEWS:
        text = f"{title}\n{body}"
        tags = list({*tags, *(_entity_hints(title, body))})[:16]
    elif itype == ItemType.PAPER:
        text = f"{title}\n{body}"
        tags = list({*tags, *(item.topics or [])})[:16]
    elif itype == ItemType.STOCK_NEWS:
        text = f"{title}\n{body}"
        sector = ""
        stock = meta.get("stock") if isinstance(meta, dict) else None
        if isinstance(stock, dict):
            sector = str(stock.get("sector") or stock.get("theme") or "")
        if sector:
            tags = list({*tags, sector})[:16]
        title = title or "股票资讯"
    elif itype == ItemType.MODEL:
        text = f"{title}\n{body}"
        community = str(meta.get("community_label") or meta.get("community") or "")
        if community:
            tags = list({*tags, community})[:16]
    elif itype == ItemType.EDUCATION:
        inst = str(meta.get("institution") or source_name or "")
        text = f"{title}\n{body}"
        if inst:
            tags = list({*tags, inst, "开放课程"})[:16]
        title = title or "教育资源"
    elif itype in {ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE}:
        text = f"{title}\n{body}"
    else:
        text = f"{title}\n{body}"

    folder = f"wiki/{type_label}"
    return WikiItem(
        id=str(item.id),
        title=title[:500],
        text_content=truncate(text, 4000) or title,
        tags=tags,
        file_url=item.url or "",
        item_type=itype,
        type_label=type_label,
        category=item.category or "",
        source_name=source_name,
        folder_path=folder,
        list_path=list_path,
    )


def _entity_hints(title: str, body: str) -> list[str]:
    """Lightweight token hints (not full NER)."""
    import re

    blob = f"{title} {body}"
    found: list[str] = []
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b", blob):
        w = m.group(1)
        if len(w) >= 3 and w.lower() not in {"the", "and", "for"}:
            found.append(w)
    for m in re.finditer(r"[\u4e00-\u9fff]{2,8}", blob):
        found.append(m.group(0))
    return found[:6]


def build_gbrain_graph(
    wiki_items: Sequence[WikiItem],
    *,
    seed_id: str | None = None,
    max_nodes: int = 120,
    max_edges: int = 200,
    max_item_nodes: int | None = None,
) -> KnowledgeGraph:
    """Core GBrain — star edges item↔concept so resource URLs stay first-class."""
    node_weights: Counter[str] = Counter()
    node_meta: dict[str, GraphNode] = {}
    edge_weights: Counter[tuple[str, str]] = Counter()
    item_ids: list[str] = []

    for wiki in wiki_items:
        concepts: list[tuple[str, str]] = []  # (kind, label)
        concepts.append(("type", wiki.type_label))
        if wiki.category:
            concepts.append(("category", wiki.category))
        for tag in wiki.tags[:8]:
            if tag and len(tag) <= 40:
                concepts.append(("tag", tag))
        if wiki.source_name:
            concepts.append(("source", wiki.source_name))
        if wiki.item_type == ItemType.EDUCATION or "开放课程" in wiki.tags:
            for t in wiki.tags:
                if t and t not in {wiki.category, "开放课程"} and len(t) <= 24:
                    concepts.append(("institution", t))
                    break

        item_nid = _node_id("item", wiki.id)
        item_ids.append(item_nid)
        node_weights[item_nid] += 3
        title_label = wiki.title[:40] + ("…" if len(wiki.title) > 40 else "")
        node_meta[item_nid] = GraphNode(
            id=item_nid,
            label=title_label or wiki.type_label,
            kind="item",
            weight=3,
            url=wiki.file_url,
            category=wiki.type_label,
            hint="点击打开原文 / 资源页",
        )

        for kind, label in concepts:
            nid = _node_id(kind, label)
            node_weights[nid] += 1
            browse = _browse_url(kind=kind, label=label, list_path=wiki.list_path)
            if nid not in node_meta:
                node_meta[nid] = GraphNode(
                    id=nid,
                    label=label,
                    kind=kind,
                    weight=1,
                    url=browse,
                    category=kind,
                    hint=_concept_hint(kind),
                )
            else:
                node_meta[nid].weight = node_weights[nid]
                if not node_meta[nid].url and browse:
                    node_meta[nid].url = browse
            # Star: item ↔ concept (keeps resources as clickable hubs)
            a, b = sorted((item_nid, nid))
            edge_weights[(a, b)] += 1

    # Prefer seed neighborhood when provided.
    keep_ids: set[str] | None = None
    if seed_id:
        seed_nid = _node_id("item", seed_id)
        neighbors = {seed_nid}
        for (a, b), _w in edge_weights.items():
            if a == seed_nid or b == seed_nid:
                neighbors.add(a)
                neighbors.add(b)
        second: set[str] = set()
        for (a, b), _w in edge_weights.items():
            if a in neighbors or b in neighbors:
                second.add(a)
                second.add(b)
        keep_ids = neighbors | second

    item_budget = max_item_nodes
    if item_budget is None:
        item_budget = max(24, int(max_nodes * 0.55))
    item_budget = min(item_budget, max_nodes - 8)

    # Always reserve slots for concrete resources (with URLs).
    ranked_items = sorted(
        ((nid, node_weights[nid]) for nid in item_ids if nid in node_meta),
        key=lambda x: -x[1],
    )
    if seed_id:
        seed_nid = _node_id("item", seed_id)
        ranked_items = sorted(
            ranked_items,
            key=lambda x: (0 if x[0] == seed_nid else 1, -x[1]),
        )

    chosen: list[GraphNode] = []
    chosen_ids: set[str] = set()
    for nid, w in ranked_items:
        if keep_ids is not None and nid not in keep_ids:
            continue
        meta = node_meta[nid]
        meta.weight = w
        chosen.append(meta)
        chosen_ids.add(nid)
        if len(chosen) >= item_budget:
            break

    # Fill remaining with strongest concept hubs still connected to chosen items.
    concept_candidates = [
        (nid, w)
        for nid, w in node_weights.items()
        if nid not in chosen_ids and node_meta.get(nid) and node_meta[nid].kind != "item"
    ]
    if keep_ids is not None:
        concept_candidates = [(n, w) for n, w in concept_candidates if n in keep_ids]
    # Prefer concepts linked to already-chosen items
    linked_concepts: Counter[str] = Counter()
    for (a, b), w in edge_weights.items():
        if a in chosen_ids and b not in chosen_ids:
            linked_concepts[b] += w
        elif b in chosen_ids and a not in chosen_ids:
            linked_concepts[a] += w
    concept_candidates.sort(
        key=lambda x: (-linked_concepts.get(x[0], 0), -x[1]),
    )
    for nid, w in concept_candidates:
        if len(chosen) >= max_nodes:
            break
        meta = node_meta[nid]
        meta.weight = w
        chosen.append(meta)
        chosen_ids.add(nid)

    edges = [
        GraphEdge(source=a, target=b, weight=w)
        for (a, b), w in edge_weights.most_common(max_edges * 4)
        if a in chosen_ids and b in chosen_ids
    ][:max_edges]

    top_links: list[dict[str, Any]] = []
    for e in edges[:30]:
        na = node_meta.get(e.source)
        nb = node_meta.get(e.target)
        if not na or not nb:
            continue
        top_links.append(
            {
                "a": na.label,
                "a_kind": na.kind,
                "b": nb.label,
                "b_kind": nb.kind,
                "weight": e.weight,
            }
        )

    echarts = _to_echarts(chosen, edges)
    return KnowledgeGraph(nodes=chosen, edges=edges, top_links=top_links, echarts=echarts)


def _concept_hint(kind: str) -> str:
    if kind == "category":
        return "点击查看该分类列表"
    if kind == "tag":
        return "点击在个人空间试搜此标签"
    if kind == "source":
        return "点击进入对应资源 Tab"
    if kind == "type":
        return "点击进入该类型列表"
    if kind == "institution":
        return "点击查看教育资源"
    return "点击查看相关内容"


def _to_echarts(nodes: list[GraphNode], edges: list[GraphEdge]) -> dict[str, Any]:
    categories = sorted({n.kind for n in nodes})
    cat_index = {c: i for i, c in enumerate(categories)}
    return {
        "categories": [
            {"name": c, "label": _KIND_LABELS_ZH.get(c, c)} for c in categories
        ],
        "nodes": [
            {
                "id": n.id,
                "name": n.label,
                "symbolSize": (
                    min(64, 22 + n.weight * 2)
                    if n.kind == "item"
                    else min(48, 12 + n.weight * 2)
                ),
                "category": cat_index.get(n.kind, 0),
                "value": n.weight,
                "url": n.url,
                "kind": n.kind,
                "kind_label": _KIND_LABELS_ZH.get(n.kind, n.kind),
                "hint": n.hint or ("点击打开" if n.url else ""),
                "clickable": bool(n.url),
                "itemStyle": {
                    "color": _KIND_COLORS.get(n.kind, "#64748b"),
                    "borderColor": "#22c55e" if n.url else "transparent",
                    "borderWidth": 2 if n.url else 0,
                },
            }
            for n in nodes
        ],
        "links": [
            {
                "source": e.source,
                "target": e.target,
                "value": e.weight,
                "lineStyle": {"width": min(5, 1 + e.weight * 0.35)},
            }
            for e in edges
        ],
        "stats": {
            "nodes": len(nodes),
            "links": len(edges),
            "items": sum(1 for n in nodes if n.kind == "item"),
            "clickable": sum(1 for n in nodes if n.url),
        },
    }


def build_knowledge_graph(
    session: Session,
    *,
    limit: int = 500,
    seed_id: UUID | str | None = None,
) -> KnowledgeGraph:
    items = list(
        session.scalars(
            select(IntelItem)
            .where(IntelItem.status != ItemStatus.REJECTED)
            .order_by(IntelItem.published_at.desc().nullslast())
            .limit(limit)
        ).all()
    )
    # When seed is set, ensure seed + neighbors are in the pool.
    if seed_id:
        seed = session.get(IntelItem, seed_id if isinstance(seed_id, UUID) else UUID(str(seed_id)))
        if seed is not None and all(i.id != seed.id for i in items):
            items = [seed, *items[: limit - 1]]

    source_names: dict[str, str] = {}
    src_ids = {i.source_id for i in items if i.source_id}
    if src_ids:
        for src in session.scalars(select(IntelSource).where(IntelSource.id.in_(src_ids))).all():
            source_names[str(src.id)] = src.name

    wiki_items = [
        adapt_intel_item(
            item,
            source_name=source_names.get(str(item.source_id), "") if item.source_id else "",
        )
        for item in items
    ]
    sid = str(seed_id) if seed_id else None
    return build_gbrain_graph(
        wiki_items,
        seed_id=sid,
        max_nodes=140,
        max_edges=220,
        max_item_nodes=70,
    )


def item_subgraph(
    session: Session,
    seed: IntelItem,
    related_items: Sequence[IntelItem],
) -> dict[str, Any]:
    """ECharts subgraph for seed + related items (drawer graph tab)."""
    # Deduplicate while keeping seed first; pull more related for richer graph.
    seen: set[str] = set()
    pool: list[IntelItem] = []
    for i in [seed, *list(related_items)[:60]]:
        key = str(i.id)
        if key in seen:
            continue
        seen.add(key)
        pool.append(i)

    src_ids = {i.source_id for i in pool if i.source_id}
    names: dict[str, str] = {}
    if src_ids:
        for src in session.scalars(select(IntelSource).where(IntelSource.id.in_(src_ids))).all():
            names[str(src.id)] = src.name
    wiki = [
        adapt_intel_item(i, source_name=names.get(str(i.source_id), "") if i.source_id else "")
        for i in pool
    ]
    graph = build_gbrain_graph(
        wiki,
        seed_id=str(seed.id),
        max_nodes=90,
        max_edges=140,
        max_item_nodes=48,
    )
    return graph.echarts


def dashboard_payload(session: Session, *, owner_id=None) -> dict[str, Any]:
    from bagel.services.search_analytics import (
        item_type_stats,
        keyword_rankings,
        search_count,
        source_stats,
    )

    graph = build_knowledge_graph(session)
    return {
        "search_count": search_count(session, owner_id=owner_id),
        "keyword_rankings": keyword_rankings(session, owner_id=owner_id),
        "type_stats": item_type_stats(session),
        "source_stats": source_stats(session),
        "graph_nodes": [
            {
                "id": n.id,
                "label": n.label,
                "kind": n.kind,
                "weight": n.weight,
                "url": n.url,
            }
            for n in graph.nodes[:60]
        ],
        "graph_links": graph.top_links,
        "echarts": graph.echarts,
    }
