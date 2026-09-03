"""Wiki compile — MD bodies on disk, transactional index in DB.

llm-wiki shaped operations (deterministic MVP, no LLM required):
  Ingest  — item MD + topic pages + edges
  Index   — index.md catalog
  Log     — append-only log.md
  Lint    — orphan topics / missing deps (returned as report)

Raw IntelItem / evidence are never modified.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus
from bagel.domain.models import IntelItem, WikiEdge, WikiPage
from bagel.pipeline.textutil import strip_html, truncate
from bagel.settings import Settings, get_settings
from bagel.taxonomy import Taxonomy, get_taxonomy, match_topics
from bagel.taxonomy.models import Topic

_SLUG_RE = re.compile(r"[^\w\u4e00-\u9fff\-]+", re.UNICODE)


def _slug(text: str, limit: int = 48) -> str:
    cleaned = _SLUG_RE.sub("-", (text or "").strip()).strip("-") or "page"
    return cleaned[:limit]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class CompileStats:
    items_written: int = 0
    items_skipped: int = 0
    topics_written: int = 0
    edges_upserted: int = 0
    lint: list[str] = field(default_factory=list)


def ensure_wiki_layout(root: Path) -> None:
    for sub in (
        "news",
        "github",
        "media",
        "wechat",
        "papers",
        "education",
        "models",
        "stocks",
        "briefs",
        "topics",
        "clusters",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
    index = root / "index.md"
    if not index.exists():
        index.write_text(
            "# Bagel Wiki\n\n由 贝果 编译。事务索引在数据库；正文在 Markdown。\n",
            encoding="utf-8",
        )
    log = root / "log.md"
    if not log.exists():
        log.write_text("# Wiki Log\n\n", encoding="utf-8")


def _item_bucket(item_type: str) -> str:
    return {
        "NEWS": "news",
        "GITHUB_REPO": "github",
        "GITHUB_RELEASE": "github",
        "MEDIA_POST": "media",
        "WECHAT_MSG": "wechat",
        "PAPER": "papers",
        "EDUCATION": "education",
        "MODEL": "models",
        "STOCK_NEWS": "stocks",
    }.get(str(item_type), "news")


def _item_text(item: IntelItem) -> str:
    title = strip_html(item.llm_title_zh or item.title) or item.title or ""
    body = strip_html(item.summary or item.content or item.llm_summary or "")
    return f"{title}\n{body}"


def topics_for_item(item: IntelItem, tax: Taxonomy | None = None) -> list[Topic]:
    tax = tax or get_taxonomy()
    return match_topics(
        _item_text(item),
        tax=tax,
        category=item.category,
        item_type=item.item_type,
        limit=5,
    )


def _upsert_page(
    session: Session,
    *,
    rel_path: str,
    slug: str,
    kind: str,
    title: str,
    content_hash: str,
    intel_item_id: UUID | None = None,
    topic_id: str | None = None,
    owner_id: UUID | None = None,
) -> WikiPage:
    row = session.scalar(select(WikiPage).where(WikiPage.rel_path == rel_path))
    now = datetime.now(UTC)
    if row is None:
        row = WikiPage(
            owner_id=owner_id,
            slug=slug,
            rel_path=rel_path,
            kind=kind,
            title=title[:512],
            intel_item_id=intel_item_id,
            topic_id=topic_id,
            content_hash=content_hash,
            compiled_at=now,
        )
        session.add(row)
    else:
        row.slug = slug
        row.kind = kind
        row.title = title[:512]
        row.intel_item_id = intel_item_id
        row.topic_id = topic_id
        row.content_hash = content_hash
        row.compiled_at = now
        if owner_id is not None:
            row.owner_id = owner_id
    return row


def _upsert_edge(
    session: Session,
    *,
    source_key: str,
    target_key: str,
    relation: str,
    weight: float = 1.0,
    reason: str | None = None,
    owner_id: UUID | None = None,
) -> None:
    row = session.scalar(
        select(WikiEdge).where(
            WikiEdge.source_key == source_key,
            WikiEdge.target_key == target_key,
            WikiEdge.relation == relation,
        )
    )
    if row is None:
        session.add(
            WikiEdge(
                owner_id=owner_id,
                source_key=source_key,
                target_key=target_key,
                relation=relation,
                weight=weight,
                reason=reason,
            )
        )
    else:
        row.weight = weight
        row.reason = reason
        if owner_id is not None:
            row.owner_id = owner_id


def _write_if_changed(path: Path, body: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = _sha(body)
    if path.exists() and _sha(path.read_text(encoding="utf-8")) == digest:
        return False
    path.write_text(body, encoding="utf-8")
    return True


def _render_item_md(item: IntelItem, topics: list[Topic]) -> str:
    title = item.llm_title_zh or item.title
    tags = ", ".join(str(t) for t in (item.tags or []))
    topic_links = ", ".join(f"[[topics/{t.id}|{t.name}]]" for t in topics) or "—"
    body = item.llm_summary or item.summary or item.content or ""
    published = item.published_at.isoformat() if item.published_at else ""
    return (
        f"# {title}\n\n"
        f"- type: `{item.item_type}`\n"
        f"- category: `{item.category or ''}`\n"
        f"- published: `{published}`\n"
        f"- url: {item.url}\n"
        f"- tags: {tags}\n"
        f"- topics: {topic_links}\n\n"
        f"## Summary\n\n{body}\n"
    )


def _render_topic_md(topic: Topic, items: list[IntelItem], deps_in: list[str], deps_out: list[str]) -> str:
    evidence = "\n".join(f"- {e}" for e in topic.evidence) or "- （暂无）"
    related = "\n".join(
        f"- [{(i.llm_title_zh or i.title)[:80]}]({i.url})" for i in items[:40]
    ) or "- （暂无关联资源）"
    prereq = "\n".join(f"- [[{p}]]" for p in deps_in) or "- （无）"
    unlocks = "\n".join(f"- [[{p}]]" for p in deps_out) or "- （无）"
    return (
        f"# {topic.name}\n\n"
        f"- id: `{topic.id}`\n"
        f"- type: `{topic.type}`\n"
        f"- subject: `{topic.subject}`\n"
        f"- domain: `{topic.domain or ''}`\n"
        f"- category: `{topic.category or ''}`\n\n"
        f"## Description\n\n{topic.description}\n\n"
        f"## Evidence\n\n{evidence}\n\n"
        f"## Prerequisites\n\n{prereq}\n\n"
        f"## Unlocks\n\n{unlocks}\n\n"
        f"## Resources\n\n{related}\n"
    )


def append_log(root: Path, entry: str) -> None:
    ensure_wiki_layout(root)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    with (root / "log.md").open("a", encoding="utf-8") as fh:
        fh.write(f"## [{stamp}] {entry}\n")


def rebuild_index_md(session: Session, root: Path) -> None:
    ensure_wiki_layout(root)
    pages = list(session.scalars(select(WikiPage).order_by(WikiPage.kind, WikiPage.title)).all())
    lines = ["# Bagel Wiki Index\n", "统一目录：全类型资源 + 主题页（MD 正文 / DB 索引）。\n"]
    by_kind: dict[str, list[WikiPage]] = {}
    for p in pages:
        by_kind.setdefault(p.kind, []).append(p)
    for kind in ("topic", "cluster", "item", "brief", "index"):
        rows = by_kind.get(kind) or []
        if not rows:
            continue
        lines.append(f"\n## {kind}\n")
        for p in rows[:500]:
            lines.append(f"- [{p.title or p.slug}]({p.rel_path}) `{p.slug}`")
    (root / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def lint_taxonomy_coverage(tax: Taxonomy, linked_topic_ids: set[str]) -> list[str]:
    issues: list[str] = []
    for topic in tax.topic_list():
        if topic.id not in linked_topic_ids and topic.centrality >= 0.7:
            issues.append(f"orphan-high-centrality:{topic.id}")
    for dep in tax.dependencies:
        if dep.strength == "hard" and (
            dep.topic_id not in linked_topic_ids or dep.prerequisite_id not in linked_topic_ids
        ):
            issues.append(f"hard-dep-partial:{dep.topic_id}->{dep.prerequisite_id}")
    return issues


def compile_wiki(
    session: Session,
    *,
    settings: Settings | None = None,
    limit: int = 400,
    owner_id: UUID | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Idempotent compile: write MD + upsert wiki_page / wiki_edge."""
    settings = settings or get_settings()
    root = settings.wiki_path
    ensure_wiki_layout(root)
    tax = get_taxonomy()
    stats = CompileStats()

    items = list(
        session.scalars(
            select(IntelItem)
            .where(IntelItem.status != ItemStatus.REJECTED)
            .order_by(IntelItem.published_at.desc().nullslast())
            .limit(limit)
        ).all()
    )

    # Seed taxonomy prerequisite edges (stable, shared).
    session.execute(
        delete(WikiEdge).where(WikiEdge.relation.in_(("prerequisite", "about", "contains")))
    )
    for dep in tax.dependencies:
        _upsert_edge(
            session,
            source_key=f"topic:{dep.topic_id}",
            target_key=f"topic:{dep.prerequisite_id}",
            relation="prerequisite",
            weight=2.0 if dep.strength == "hard" else 1.0,
            reason=dep.reason,
            owner_id=owner_id,
        )
        stats.edges_upserted += 1

    topic_items: dict[str, list[IntelItem]] = {t.id: [] for t in tax.topic_list()}
    linked_topics: set[str] = set()

    for item in items:
        topics = topics_for_item(item, tax)
        for t in topics:
            topic_items.setdefault(t.id, []).append(item)
            linked_topics.add(t.id)

        bucket = _item_bucket(item.item_type)
        month = (
            item.published_at.strftime("%Y-%m")
            if item.published_at is not None
            else datetime.now(UTC).strftime("%Y-%m")
        )
        fname = f"{_slug(item.title)}-{str(item.id)[:8]}.md"
        rel = f"{bucket}/{month}/{fname}"
        path = root / rel
        body = _render_item_md(item, topics)
        digest = _sha(body)
        existing = session.scalar(select(WikiPage).where(WikiPage.rel_path == rel))
        if (
            not force
            and existing
            and existing.content_hash == digest
            and path.exists()
        ):
            stats.items_skipped += 1
        else:
            _write_if_changed(path, body)
            stats.items_written += 1
        _upsert_page(
            session,
            rel_path=rel,
            slug=f"item-{str(item.id)[:8]}",
            kind="item",
            title=(item.llm_title_zh or item.title or "")[:512],
            content_hash=digest,
            intel_item_id=item.id,
            topic_id=topics[0].id if topics else None,
            owner_id=owner_id or item.owner_id,
        )
        item_key = f"item:{item.id}"
        for t in topics:
            _upsert_edge(
                session,
                source_key=item_key,
                target_key=f"topic:{t.id}",
                relation="about",
                weight=1.0 + t.centrality,
                reason="taxonomy match",
                owner_id=owner_id or item.owner_id,
            )
            stats.edges_upserted += 1

    # Topic pages
    deps_in: dict[str, list[str]] = {t.id: [] for t in tax.topic_list()}
    deps_out: dict[str, list[str]] = {t.id: [] for t in tax.topic_list()}
    for dep in tax.dependencies:
        deps_in[dep.topic_id].append(dep.prerequisite_id)
        deps_out[dep.prerequisite_id].append(dep.topic_id)

    for topic in tax.topic_list():
        rel = f"topics/{topic.id}.md"
        body = _render_topic_md(
            topic,
            topic_items.get(topic.id, []),
            deps_in.get(topic.id, []),
            deps_out.get(topic.id, []),
        )
        digest = _sha(body)
        if _write_if_changed(root / rel, body) or force:
            stats.topics_written += 1
        _upsert_page(
            session,
            rel_path=rel,
            slug=topic.id,
            kind="topic",
            title=topic.name,
            content_hash=digest,
            topic_id=topic.id,
            owner_id=owner_id,
        )

    # Cluster summaries (MD only + index row)
    for cluster in tax.clusters.values():
        rel = f"clusters/{cluster.id}.md"
        topic_lines = "\n".join(f"- [[{tid}]]" for tid in cluster.topic_ids)
        body = (
            f"# {cluster.name}\n\n"
            f"- id: `{cluster.id}`\n"
            f"- subject: `{cluster.subject}`\n"
            f"- domain: `{cluster.domain}`\n\n"
            f"{cluster.summary}\n\n"
            f"## Topics\n\n{topic_lines}\n"
        )
        digest = _sha(body)
        _write_if_changed(root / rel, body)
        _upsert_page(
            session,
            rel_path=rel,
            slug=cluster.id,
            kind="cluster",
            title=cluster.name,
            content_hash=digest,
            owner_id=owner_id,
        )
        for tid in cluster.topic_ids:
            _upsert_edge(
                session,
                source_key=f"cluster:{cluster.id}",
                target_key=f"topic:{tid}",
                relation="contains",
                weight=1.0,
                reason="cluster membership",
                owner_id=owner_id,
            )
            stats.edges_upserted += 1

    stats.lint = lint_taxonomy_coverage(tax, linked_topics)
    rebuild_index_md(session, root)
    append_log(
        root,
        f"ingest | items={stats.items_written} skip={stats.items_skipped} "
        f"topics={stats.topics_written} edges≈{stats.edges_upserted} lint={len(stats.lint)}",
    )
    session.flush()
    return {
        "items_written": stats.items_written,
        "items_skipped": stats.items_skipped,
        "topics_written": stats.topics_written,
        "edges_upserted": stats.edges_upserted,
        "lint": stats.lint,
        "wiki_dir": root.as_posix(),
        "display_wiki_dir": settings.wiki_dir,
    }
