"""Load / validate / match Bagel taxonomy seed JSON."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from bagel.taxonomy.models import Cluster, Dependency, Topic

_SEED_DIR = Path(__file__).resolve().parent / "seed"
_TOPIC_ID_RE = re.compile(r"^tp_[a-z0-9_]+$")
_CLUSTER_ID_RE = re.compile(r"^cl_[a-z0-9_]+$")


@dataclass(slots=True)
class Taxonomy:
    version: str
    topics: dict[str, Topic] = field(default_factory=dict)
    dependencies: list[Dependency] = field(default_factory=list)
    clusters: dict[str, Cluster] = field(default_factory=dict)
    category_index: dict[str, str] = field(default_factory=dict)

    def get(self, topic_id: str) -> Topic | None:
        return self.topics.get(topic_id)

    def topic_list(self) -> list[Topic]:
        return list(self.topics.values())


def seed_dir() -> Path:
    return _SEED_DIR


def _parse_topic(raw: dict) -> Topic:
    tid = str(raw["id"])
    if not _TOPIC_ID_RE.match(tid):
        raise ValueError(f"invalid topic id: {tid}")
    aliases = tuple(str(a).strip() for a in (raw.get("aliases") or []) if str(a).strip())
    evidence = tuple(str(e) for e in (raw.get("evidence") or []) if str(e).strip())
    return Topic(
        id=tid,
        type=raw["type"],  # type: ignore[arg-type]
        subject=str(raw["subject"]),
        name=str(raw["name"]),
        description=str(raw.get("description") or ""),
        domain=(str(raw["domain"]) if raw.get("domain") else None),
        aliases=aliases,
        category=(str(raw["category"]) if raw.get("category") else None),
        centrality=float(raw.get("centrality") or 0.0),
        evidence=evidence,
        parent_id=(str(raw["parentId"]) if raw.get("parentId") else None),
    )


def _parse_dep(raw: dict) -> Dependency:
    return Dependency(
        topic_id=str(raw["topicId"]),
        prerequisite_id=str(raw["prerequisiteId"]),
        strength=str(raw.get("strength") or "soft"),  # type: ignore[arg-type]
        reason=str(raw.get("reason") or ""),
    )


def _parse_cluster(raw: dict) -> Cluster:
    cid = str(raw["id"])
    if not _CLUSTER_ID_RE.match(cid):
        raise ValueError(f"invalid cluster id: {cid}")
    return Cluster(
        id=cid,
        subject=str(raw["subject"]),
        domain=str(raw["domain"]),
        name=str(raw["name"]),
        summary=str(raw.get("summary") or ""),
        topic_ids=tuple(str(t) for t in (raw.get("topicIds") or [])),
    )


def load_taxonomy(*, root: Path | None = None) -> Taxonomy:
    """Load taxonomy from seed JSON (or alternate root for tests)."""
    global _SEED_DIR
    base = root or _SEED_DIR
    topics_raw = json.loads((base / "topics.json").read_text(encoding="utf-8"))
    deps_raw = json.loads((base / "dependencies.json").read_text(encoding="utf-8"))
    clusters_raw = json.loads((base / "clusters.json").read_text(encoding="utf-8"))

    topics: dict[str, Topic] = {}
    for raw in topics_raw.get("topics") or []:
        topic = _parse_topic(raw)
        topics[topic.id] = topic

    deps = [_parse_dep(d) for d in deps_raw.get("dependencies") or []]
    clusters: dict[str, Cluster] = {}
    for raw in clusters_raw.get("clusters") or []:
        cluster = _parse_cluster(raw)
        clusters[cluster.id] = cluster

    # Highest centrality wins as the primary topic for a coarse category label.
    category_index: dict[str, str] = {}
    for topic in sorted(topics.values(), key=lambda t: -t.centrality):
        if topic.category and topic.category not in category_index:
            category_index[topic.category] = topic.id

    tax = Taxonomy(
        version=str(topics_raw.get("version") or "v1"),
        topics=topics,
        dependencies=deps,
        clusters=clusters,
        category_index=category_index,
    )
    validate_taxonomy(tax)
    return tax


def validate_taxonomy(tax: Taxonomy) -> None:
    """Referential integrity: deps and clusters point at known topics."""
    ids = set(tax.topics)
    for dep in tax.dependencies:
        if dep.topic_id not in ids:
            raise ValueError(f"dependency topic missing: {dep.topic_id}")
        if dep.prerequisite_id not in ids:
            raise ValueError(f"dependency prerequisite missing: {dep.prerequisite_id}")
        if dep.topic_id == dep.prerequisite_id:
            raise ValueError(f"self-dependency: {dep.topic_id}")
        if dep.strength not in {"hard", "soft"}:
            raise ValueError(f"bad strength: {dep.strength}")
    for topic in tax.topics.values():
        if topic.parent_id and topic.parent_id not in ids:
            raise ValueError(f"parent missing for {topic.id}: {topic.parent_id}")
        if topic.parent_id == topic.id:
            raise ValueError(f"self-parent: {topic.id}")
    for cluster in tax.clusters.values():
        for tid in cluster.topic_ids:
            if tid not in ids:
                raise ValueError(f"cluster {cluster.id} unknown topic {tid}")


def children_of(tax: Taxonomy, topic_id: str) -> list[Topic]:
    return [t for t in tax.topic_list() if t.parent_id == topic_id]


@lru_cache(maxsize=1)
def get_taxonomy() -> Taxonomy:
    return load_taxonomy()


def clear_taxonomy_cache() -> None:
    get_taxonomy.cache_clear()


def topic_by_category(category: str | None, tax: Taxonomy | None = None) -> Topic | None:
    if not category:
        return None
    tax = tax or get_taxonomy()
    tid = tax.category_index.get(category)
    return tax.get(tid) if tid else None


def match_topics(
    text: str,
    *,
    tax: Taxonomy | None = None,
    category: str | None = None,
    item_type: str | None = None,
    limit: int = 6,
) -> list[Topic]:
    """Alias / category / type heuristic → ordered topic hits (longest alias wins)."""
    tax = tax or get_taxonomy()
    blob = (text or "").lower()
    scored: dict[str, int] = {}

    if category:
        primary = topic_by_category(category, tax)
        if primary:
            scored[primary.id] = max(scored.get(primary.id, 0), 1000 + int(primary.centrality * 100))

    # Type priors for unified multi-resource view
    type_priors = {
        "PAPER": "tp_paper",
        "GITHUB_REPO": "tp_github",
        "GITHUB_RELEASE": "tp_github",
        "MODEL": "tp_model_hub",
        "EDUCATION": "tp_ocw",
        "STOCK_NEWS": "tp_stock_ai",
        "MEDIA_POST": "tp_media",
        "WECHAT_MSG": "tp_media",
    }
    if item_type and item_type in type_priors:
        tid = type_priors[item_type]
        if tid in tax.topics:
            scored[tid] = max(scored.get(tid, 0), 400)

    for topic in tax.topics.values():
        best = -1
        for alias in topic.aliases:
            needle = alias.lower()
            if needle and needle in blob and len(needle) > best:
                best = len(needle)
        if best >= 0:
            scored[topic.id] = max(
                scored.get(topic.id, 0),
                best * 10 + int(topic.centrality * 50),
            )

    ranked = sorted(scored.items(), key=lambda x: -x[1])
    out: list[Topic] = []
    for tid, _ in ranked[:limit]:
        t = tax.get(tid)
        if t:
            out.append(t)
    return out
