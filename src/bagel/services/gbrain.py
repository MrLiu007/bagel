"""GBrain — unified knowledge graph for all user resources.

Projection sources (priority):
1. Taxonomy topics + prerequisite edges (structured)
2. WikiEdge about/contains links when compiled
3. Light fallback: category / type (never raw regex tag soup)

Heterogeneous IntelItem types share one graph so the user sees one space.
No external graph / vector DB.
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
from bagel.domain.models import IntelItem, IntelSource, WikiEdge
from bagel.pipeline.textutil import strip_html, truncate
from bagel.taxonomy import get_taxonomy, match_topics
from bagel.taxonomy.models import Topic

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
    "topic": "#0d9488",
    "cluster": "#7c3aed",
    "source": "#f59e0b",
    "item": "#ef4444",
    "institution": "#22c55e",
    "tag": "#94a3b8",
}

_KIND_LABELS_ZH: dict[str, str] = {
    "type": "类型",
    "category": "分类",
    "topic": "主题",
    "cluster": "主题簇",
    "source": "数据源",
    "item": "资源",
    "institution": "院校",
    "tag": "标签",
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
    topic_ids: list[str] = field(default_factory=list)


@dataclass
class GraphNode:
    id: str
    label: str
    kind: str
    weight: int = 0
    url: str = ""
    category: str = ""
    hint: str = ""
    subject: str = ""
    description: str = ""
    parent_id: str = ""
    filter_key: str = ""


@dataclass
class GraphEdge:
    source: str
    target: str
    weight: int
    relation: str = "about"


@dataclass
class KnowledgeGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    top_links: list[dict[str, Any]] = field(default_factory=list)
    echarts: dict[str, Any] = field(default_factory=dict)


def _node_id(kind: str, label: str) -> str:
    return f"{kind}:{label}"


def _browse_url(*, kind: str, label: str, list_path: str, topic_id: str = "") -> str:
    path = list_path or "/news"
    q = quote(label, safe="")
    if kind == "topic":
        return f"/briefs/space?view=graph&q={quote(topic_id or label, safe='')}"
    if kind == "cluster":
        return f"/briefs/space?view=graph&q={q}"
    if kind == "category":
        return f"{path}?category={q}"
    if kind == "source":
        return path
    if kind == "type":
        return path
    if kind == "institution":
        return "/education"
    if kind == "tag":
        return f"/briefs/space?q={q}"
    return ""


def adapt_intel_item(item: IntelItem, *, source_name: str = "") -> WikiItem:
    """Map heterogeneous IntelItem → WikiItem (adapter layer)."""
    itype = item.item_type or ItemType.NEWS
    type_label = _TYPE_LABELS.get(itype, itype)
    title = strip_html(item.llm_title_zh or item.title) or item.title or ""
    body = strip_html(item.summary or item.content or item.llm_summary or "")
    tags = [str(t) for t in (item.tags or []) if t][:8]
    meta = item.metadata_ or {}
    list_path = _LIST_PATHS.get(itype, "/news")
    text = f"{title}\n{body}"

    if itype == ItemType.STOCK_NEWS:
        stock = meta.get("stock") if isinstance(meta, dict) else None
        if isinstance(stock, dict):
            sector = str(stock.get("sector") or stock.get("theme") or "")
            if sector:
                tags = list({*tags, sector})[:10]
        title = title or "股票资讯"
    elif itype == ItemType.MODEL:
        community = str(meta.get("community_label") or meta.get("community") or "")
        if community:
            tags = list({*tags, community})[:10]
    elif itype == ItemType.EDUCATION:
        inst = str(meta.get("institution") or source_name or "")
        if inst:
            tags = list({*tags, inst})[:10]
        title = title or "教育资源"
    elif itype == ItemType.PAPER:
        tags = list({*tags, *(item.topics or [])})[:10]

    matched = match_topics(
        text,
        category=item.category,
        item_type=itype,
        limit=5,
    )
    # Prefer persisted taxonomy ids in metadata when present
    meta_ids = []
    if isinstance(meta, dict):
        raw_ids = meta.get("taxonomy_ids") or meta.get("topic_ids") or []
        if isinstance(raw_ids, list):
            meta_ids = [str(x) for x in raw_ids if x]
    topic_ids = meta_ids or [t.id for t in matched]

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
        topic_ids=topic_ids,
    )


def _ensure_node(
    node_meta: dict[str, GraphNode],
    node_weights: Counter[str],
    *,
    nid: str,
    label: str,
    kind: str,
    weight_delta: int,
    url: str,
    hint: str,
    subject: str = "",
    description: str = "",
    parent_id: str = "",
    filter_key: str = "",
) -> None:
    node_weights[nid] += weight_delta
    if nid not in node_meta:
        node_meta[nid] = GraphNode(
            id=nid,
            label=label,
            kind=kind,
            weight=weight_delta,
            url=url,
            category=kind,
            hint=hint,
            subject=subject,
            description=description,
            parent_id=parent_id,
            filter_key=filter_key or subject or kind,
        )
    else:
        node_meta[nid].weight = node_weights[nid]
        if not node_meta[nid].url and url:
            node_meta[nid].url = url
        if description and not node_meta[nid].description:
            node_meta[nid].description = description
        if subject and not node_meta[nid].subject:
            node_meta[nid].subject = subject
        if filter_key and not node_meta[nid].filter_key:
            node_meta[nid].filter_key = filter_key


def build_gbrain_graph(
    wiki_items: Sequence[WikiItem],
    *,
    seed_id: str | None = None,
    max_nodes: int = 120,
    max_edges: int = 200,
    max_item_nodes: int | None = None,
    wiki_edges: Sequence[tuple[str, str, str, float]] | None = None,
) -> KnowledgeGraph:
    """Core GBrain — resource nodes + taxonomy topics (+ optional compiled edges)."""
    tax = get_taxonomy()
    node_weights: Counter[str] = Counter()
    node_meta: dict[str, GraphNode] = {}
    edge_weights: Counter[tuple[str, str, str]] = Counter()
    item_ids: list[str] = []

    def add_edge(a: str, b: str, relation: str, w: int = 1) -> None:
        if a == b:
            return
        lo, hi = (a, b) if a < b else (b, a)
        edge_weights[(lo, hi, relation)] += w

    # Taxonomy prerequisite skeleton (always available)
    for dep in tax.dependencies:
        a = _node_id("topic", dep.topic_id)
        b = _node_id("topic", dep.prerequisite_id)
        ta = tax.get(dep.topic_id)
        tb = tax.get(dep.prerequisite_id)
        if ta:
            meta = _topic_meta(ta)
            _ensure_node(
                node_meta,
                node_weights,
                nid=a,
                label=ta.name,
                kind="topic",
                weight_delta=1,
                url=_browse_url(kind="topic", label=ta.name, list_path="/briefs/space", topic_id=ta.id),
                **meta,
            )
        if tb:
            meta = _topic_meta(tb)
            _ensure_node(
                node_meta,
                node_weights,
                nid=b,
                label=tb.name,
                kind="topic",
                weight_delta=1,
                url=_browse_url(kind="topic", label=tb.name, list_path="/briefs/space", topic_id=tb.id),
                **meta,
            )
        add_edge(a, b, "prerequisite", 2 if dep.strength == "hard" else 1)

    for cluster in tax.clusters.values():
        cid = _node_id("cluster", cluster.id)
        _ensure_node(
            node_meta,
            node_weights,
            nid=cid,
            label=cluster.name,
            kind="cluster",
            weight_delta=2,
            url=_browse_url(kind="cluster", label=cluster.name, list_path="/briefs/space"),
            hint="主题簇 · 点击打开知识卡片",
            subject=cluster.subject,
            description=cluster.summary,
            filter_key=cluster.subject,
        )
        for tid in cluster.topic_ids:
            topic = tax.get(tid)
            if not topic:
                continue
            tnid = _node_id("topic", tid)
            meta = _topic_meta(topic)
            _ensure_node(
                node_meta,
                node_weights,
                nid=tnid,
                label=topic.name,
                kind="topic",
                weight_delta=1,
                url=_browse_url(
                    kind="topic", label=topic.name, list_path="/briefs/space", topic_id=topic.id
                ),
                **meta,
            )
            add_edge(cid, tnid, "contains", 1)

    for wiki in wiki_items:
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
            hint="资源节点 · 点击打开知识卡片",
            subject=wiki.type_label,
            description=(wiki.text_content or "")[:280],
            filter_key=wiki.type_label or "资源",
        )

        # Type hub (unified multi-type view)
        type_nid = _node_id("type", wiki.type_label)
        _ensure_node(
            node_meta,
            node_weights,
            nid=type_nid,
            label=wiki.type_label,
            kind="type",
            weight_delta=1,
            url=_browse_url(kind="type", label=wiki.type_label, list_path=wiki.list_path),
            hint="类型枢纽",
            subject=wiki.type_label,
            filter_key=wiki.type_label,
        )
        add_edge(item_nid, type_nid, "typed_as", 1)

        topics: list[Topic] = []
        for tid in wiki.topic_ids:
            t = tax.get(tid)
            if t:
                topics.append(t)
        if not topics and wiki.category:
            from bagel.taxonomy import topic_by_category

            t = topic_by_category(wiki.category, tax)
            if t:
                topics.append(t)

        for topic in topics:
            tnid = _node_id("topic", topic.id)
            meta = _topic_meta(topic)
            _ensure_node(
                node_meta,
                node_weights,
                nid=tnid,
                label=topic.name,
                kind="topic",
                weight_delta=2,
                url=_browse_url(
                    kind="topic",
                    label=topic.name,
                    list_path=wiki.list_path,
                    topic_id=topic.id,
                ),
                **meta,
            )
            add_edge(item_nid, tnid, "about", 2)

        if wiki.source_name:
            snid = _node_id("source", wiki.source_name)
            _ensure_node(
                node_meta,
                node_weights,
                nid=snid,
                label=wiki.source_name[:40],
                kind="source",
                weight_delta=1,
                url=_browse_url(kind="source", label=wiki.source_name, list_path=wiki.list_path),
                hint="点击进入对应资源 Tab",
            )
            add_edge(item_nid, snid, "from", 1)

        if wiki.item_type == ItemType.EDUCATION:
            for t in wiki.tags[:2]:
                if t and len(t) <= 24:
                    iid = _node_id("institution", t)
                    _ensure_node(
                        node_meta,
                        node_weights,
                        nid=iid,
                        label=t,
                        kind="institution",
                        weight_delta=1,
                        url="/education",
                        hint="点击查看教育资源",
                    )
                    add_edge(item_nid, iid, "at", 1)
                    break

    # Optional compiled wiki edges (item:uuid / topic:id keys)
    if wiki_edges:
        for src, tgt, rel, w in wiki_edges:
            sa = _wiki_key_to_nid(src, tax)
            tb = _wiki_key_to_nid(tgt, tax)
            if not sa or not tb:
                continue
            for nid, kind in (sa, tb):
                if nid in node_meta:
                    continue
                if kind == "topic":
                    topic = tax.get(nid.split(":", 1)[-1])
                    if topic:
                        _ensure_node(
                            node_meta,
                            node_weights,
                            nid=nid,
                            label=topic.name,
                            kind="topic",
                            weight_delta=1,
                            url=_browse_url(
                                kind="topic",
                                label=topic.name,
                                list_path="/briefs/space",
                                topic_id=topic.id,
                            ),
                            hint="主题节点",
                        )
                elif kind == "cluster":
                    cluster = tax.clusters.get(nid.split(":", 1)[-1])
                    if cluster:
                        _ensure_node(
                            node_meta,
                            node_weights,
                            nid=nid,
                            label=cluster.name,
                            kind="cluster",
                            weight_delta=1,
                            url=_browse_url(
                                kind="cluster",
                                label=cluster.name,
                                list_path="/briefs/space",
                            ),
                            hint="主题簇",
                        )
            if sa[0] in node_meta and tb[0] in node_meta:
                add_edge(sa[0], tb[0], rel or "about", max(1, int(w)))

    keep_ids: set[str] | None = None
    if seed_id:
        seed_nid = _node_id("item", seed_id)
        neighbors = {seed_nid}
        for (a, b, _r), _w in edge_weights.items():
            if a == seed_nid or b == seed_nid:
                neighbors.add(a)
                neighbors.add(b)
        second: set[str] = set()
        for (a, b, _r), _w in edge_weights.items():
            if a in neighbors or b in neighbors:
                second.add(a)
                second.add(b)
        keep_ids = neighbors | second

    item_budget = max_item_nodes
    if item_budget is None:
        item_budget = max(24, int(max_nodes * 0.55))
    item_budget = min(item_budget, max_nodes - 12)

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

    concept_candidates = [
        (nid, w)
        for nid, w in node_weights.items()
        if nid not in chosen_ids and node_meta.get(nid) and node_meta[nid].kind != "item"
    ]
    if keep_ids is not None:
        concept_candidates = [(n, w) for n, w in concept_candidates if n in keep_ids]
    linked_concepts: Counter[str] = Counter()
    for (a, b, _r), w in edge_weights.items():
        if a in chosen_ids and b not in chosen_ids:
            linked_concepts[b] += w
        elif b in chosen_ids and a not in chosen_ids:
            linked_concepts[a] += w
    # Prefer topics / clusters over weak hubs
    kind_boost = {"topic": 3, "cluster": 2, "type": 1, "source": 1, "institution": 1}

    def _concept_key(pair: tuple[str, int]) -> tuple:
        nid, w = pair
        kind = node_meta[nid].kind
        return (-linked_concepts.get(nid, 0), -kind_boost.get(kind, 0), -w)

    concept_candidates.sort(key=_concept_key)
    for nid, w in concept_candidates:
        if len(chosen) >= max_nodes:
            break
        meta = node_meta[nid]
        meta.weight = w
        chosen.append(meta)
        chosen_ids.add(nid)

    # Prefer semantic relations when trimming
    rel_priority = {
        "about": 0,
        "prerequisite": 1,
        "contains": 2,
        "typed_as": 3,
        "from": 4,
        "at": 5,
    }
    ranked_edges = sorted(
        edge_weights.items(),
        key=lambda x: (rel_priority.get(x[0][2], 9), -x[1]),
    )
    edges: list[GraphEdge] = []
    for (a, b, rel), w in ranked_edges:
        if a in chosen_ids and b in chosen_ids:
            edges.append(GraphEdge(source=a, target=b, weight=w, relation=rel))
        if len(edges) >= max_edges:
            break

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
                "relation": e.relation,
            }
        )

    echarts = _to_echarts(chosen, edges)
    return KnowledgeGraph(nodes=chosen, edges=edges, top_links=top_links, echarts=echarts)


def _wiki_key_to_nid(key: str, tax) -> tuple[str, str] | None:
    if key.startswith("item:"):
        return _node_id("item", key.split(":", 1)[1]), "item"
    if key.startswith("topic:"):
        tid = key.split(":", 1)[1]
        if tax.get(tid):
            return _node_id("topic", tid), "topic"
    if key.startswith("cluster:"):
        cid = key.split(":", 1)[1]
        if cid in tax.clusters:
            return _node_id("cluster", cid), "cluster"
    return None



# Fixed resource channels for SUBJECTS toggle (never taxonomy subjects like AI).
_RESOURCE_CHANNELS: tuple[tuple[str, str, str], ...] = (
    ("新闻", "新闻", "#ef4444"),
    ("GitHub", "GitHub项目", "#f59e0b"),
    ("教育", "教育", "#22c55e"),
    ("论文", "论文", "#8b5cf6"),
    ("模型", "模型", "#06b6d4"),
    ("股票", "股票", "#eab308"),
    ("自媒体", "自媒体", "#f97316"),
    ("微信", "微信", "#84cc16"),
)


def _subject_filters(nodes: list[GraphNode]) -> list[dict[str, Any]]:
    """SUBJECTS = 8 resource channels only (新闻 / GitHub项目 / …)."""
    counts: Counter[str] = Counter()
    for n in nodes:
        if n.kind == "item" and n.category:
            counts[n.category] += 1
        elif n.kind == "type" and n.label:
            counts[n.label] += 1
    out: list[dict[str, Any]] = []
    for key, label, color in _RESOURCE_CHANNELS:
        out.append(
            {
                "key": key,
                "label": label,
                "count": int(counts.get(key, 0)),
                "color": color,
            }
        )
    return out

def _topic_meta(topic: Topic) -> dict[str, str]:
    return {
        "subject": topic.subject,
        "description": topic.description,
        "parent_id": topic.parent_id or "",
        # Topics are not SUBJECTS channels — keep empty so filters only hit resources.
        "filter_key": "",
        "hint": "主题枢纽 · 点击查看挂载资源与摘要",
    }


def _kind_height(kind: str, type_label: str = "", *, parent_id: str = "") -> float:
    """Y-axis layer (Marble-style): height encodes resource / concept role."""
    base = {
        "cluster": 0.0,
        "type": 35.0,
        "source": 45.0,
        "topic": 90.0,
        "institution": 110.0,
        "tag": 70.0,
        "category": 80.0,
        "item": 150.0,
    }.get(kind, 60.0)
    if kind == "topic" and parent_id:
        return base + 28.0  # subtopics sit slightly above parents
    if kind != "item":
        return base
    type_boost = {
        "新闻": 0.0,
        "论文": 25.0,
        "教育": 50.0,
        "GitHub": 75.0,
        "模型": 100.0,
        "股票": 125.0,
        "自媒体": 150.0,
        "微信": 160.0,
    }.get(type_label, 20.0)
    return base + type_boost


def _to_echarts(nodes: list[GraphNode], edges: list[GraphEdge]) -> dict[str, Any]:
    categories = sorted({n.kind for n in nodes})
    cat_index = {c: i for i, c in enumerate(categories)}
    resource_count = sum(1 for n in nodes if n.kind == "item")
    topic_count = sum(1 for n in nodes if n.kind == "topic")
    cluster_count = sum(1 for n in nodes if n.kind == "cluster")
    prereq_count = sum(1 for e in edges if e.relation == "prerequisite")
    about_count = sum(1 for e in edges if e.relation == "about")
    type_layers: dict[str, int] = Counter()
    for n in nodes:
        if n.kind == "item":
            type_layers[n.category or "资源"] += 1

    payload_nodes = []
    for n in nodes:
        height = _kind_height(n.kind, n.category if n.kind == "item" else "", parent_id=n.parent_id)
        payload_nodes.append(
            {
                "id": n.id,
                "name": n.label,
                "symbolSize": (
                    min(64, 22 + n.weight * 2)
                    if n.kind == "item"
                    else min(52, 14 + n.weight * 2)
                ),
                "category": cat_index.get(n.kind, 0),
                "value": n.weight,
                "url": n.url,
                "kind": n.kind,
                "kind_label": _KIND_LABELS_ZH.get(n.kind, n.kind),
                "type_label": n.category if n.kind == "item" else "",
                "hint": n.hint or ("点击打开" if n.url else ""),
                "clickable": bool(n.url),
                "subject": n.subject,
                "description": (n.description or "")[:400],
                "parent_id": n.parent_id,
                "filter_key": n.filter_key or n.subject or n.kind,
                "topic_id": n.id.split(":", 1)[-1] if n.kind == "topic" else "",
                "height": height,
                "fy": height,
                "val": max(2, min(14, 3 + n.weight)),
                "color": _KIND_COLORS.get(n.kind, "#64748b"),
                "itemStyle": {
                    "color": _KIND_COLORS.get(n.kind, "#64748b"),
                    "borderColor": "#22c55e" if n.url else "transparent",
                    "borderWidth": 2 if n.url else 0,
                },
            }
        )

    return {
        "categories": [
            {"name": c, "label": _KIND_LABELS_ZH.get(c, c)} for c in categories
        ],
        "nodes": payload_nodes,
        "links": [
            {
                "source": e.source,
                "target": e.target,
                "value": e.weight,
                "relation": e.relation,
                "lineStyle": {
                    "width": min(5, 1 + e.weight * 0.35),
                    "type": "dashed" if e.relation == "prerequisite" else "solid",
                },
            }
            for e in edges
        ],
        # Never use key "items" — Jinja dict.items collides with attribute access.
        "stats": {
            "nodes": len(nodes),
            "links": len(edges),
            "resources": resource_count,
            "topics": topic_count,
            "clusters": cluster_count,
            "prerequisites": prereq_count,
            "about": about_count,
            "clickable": sum(1 for n in nodes if n.url),
            "type_layers": [
                {"label": k, "count": v} for k, v in sorted(type_layers.items(), key=lambda x: -x[1])
            ],
            "subjects": _subject_filters(nodes),
        },
    }


def _load_wiki_edges(session: Session, *, limit: int = 2000) -> list[tuple[str, str, str, float]]:
    try:
        rows = list(session.scalars(select(WikiEdge).limit(limit)).all())
    except Exception:
        # Degraded: migration not applied yet / empty schema in tests.
        session.rollback()
        return []
    return [(r.source_key, r.target_key, r.relation, float(r.weight or 1)) for r in rows]


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
        wiki_edges=_load_wiki_edges(session),
    )


def item_subgraph(
    session: Session,
    seed: IntelItem,
    related_items: Sequence[IntelItem],
) -> dict[str, Any]:
    """ECharts subgraph for seed + related items (drawer graph tab)."""
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
        wiki_edges=_load_wiki_edges(session),
    )
    return graph.echarts


def dashboard_payload(session: Session, *, owner_id=None) -> dict[str, Any]:
    from bagel.services.search_analytics import (
        item_type_stats,
        keyword_rankings,
        search_count,
        source_stats,
    )
    from bagel.taxonomy import get_taxonomy

    graph = build_knowledge_graph(session)
    tax = get_taxonomy()
    gstats = graph.echarts.get("stats") or {}
    hard = sum(1 for d in tax.dependencies if d.strength == "hard")
    soft = sum(1 for d in tax.dependencies if d.strength == "soft")
    overview = {
        "topics": len(tax.topics),
        "dependencies": len(tax.dependencies),
        "hard_deps": hard,
        "soft_deps": soft,
        "clusters": len(tax.clusters),
        "graph_nodes": gstats.get("nodes", len(graph.nodes)),
        "graph_links": gstats.get("links", len(graph.edges)),
        "resources": gstats.get("resources", 0),
        "graph_topics": gstats.get("topics", 0),
        "prerequisites": gstats.get("prerequisites", 0),
        "type_layers": gstats.get("type_layers") or [],
        "version": tax.version,
    }
    return {
        "search_count": search_count(session, owner_id=owner_id),
        "keyword_rankings": keyword_rankings(session, owner_id=owner_id),
        "type_stats": item_type_stats(session),
        "source_stats": source_stats(session),
        "taxonomy": {
            "version": tax.version,
            "topics": len(tax.topics),
            "dependencies": len(tax.dependencies),
            "clusters": len(tax.clusters),
        },
        "overview": overview,
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
