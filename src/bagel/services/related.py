"""Related-item discovery — core keywords from summary (摘要).

Titles are often meaningless clickbait; tags are too coarse.
Primary signal: overlapping core keywords extracted from summary/content.
Secondary: same author / org.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from bagel.domain.enums import ItemStatus, ItemType
from bagel.domain.models import IntelItem
from bagel.pipeline.category import _ALIAS_GROUPS
from bagel.pipeline.textutil import strip_html
from bagel.storage.repositories import ItemRepository

_AUTHOR_SPLIT = re.compile(r"[,;，、/|&]+|\band\b|\b和\b", re.I)
_EN_TOKEN = re.compile(r"[a-z][a-z0-9\-]{2,}|[A-Z]{2,}[a-z0-9\-]*|[a-z0-9]+(?:/[a-z0-9]+)+")

# Generic fillers — never treat as core keywords.
_STOP = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "for",
    "in",
    "on",
    "at",
    "by",
    "with",
    "from",
    "into",
    "via",
    "vs",
    "is",
    "are",
    "be",
    "as",
    "it",
    "this",
    "that",
    "these",
    "those",
    "new",
    "using",
    "based",
    "towards",
    "toward",
    "about",
    "over",
    "under",
    "after",
    "before",
    "than",
    "then",
    "also",
    "just",
    "more",
    "most",
    "such",
    "into",
    "our",
    "your",
    "their",
    "will",
    "can",
    "may",
    "have",
    "has",
    "been",
    "were",
    "was",
    "which",
    "where",
    "when",
    "what",
    "how",
    "why",
    "who",
    "not",
    "no",
    "yes",
    "all",
    "any",
    "each",
    "per",
    "via",
    "的",
    "了",
    "与",
    "和",
    "及",
    "或",
    "在",
    "对",
    "为",
    "等",
    "中",
    "上",
    "下",
    "一个",
    "一种",
    "基于",
    "关于",
    "以及",
    "如何",
    "什么",
    "我们",
    "他们",
    "这个",
    "那个",
    "可以",
    "进行",
    "通过",
    "实现",
    "使用",
    "开源",
    "发布",
    "更新",
    "介绍",
    "分享",
    "表示",
    "指出",
    "认为",
    "显示",
    "包括",
    "其中",
    "如果",
    "因为",
    "所以",
    "但是",
    "而且",
    "同时",
    "已经",
    "还是",
    "或者",
    "不是",
    "没有",
    "一些",
    "这些",
    "那些",
    "自己",
    "他们",
    "大家",
    "记者",
    "消息",
    "近日",
    "今日",
    "目前",
    "相关",
    "内容",
    "文章",
    "本文",
    "原文",
    "链接",
    "点击",
    "查看",
    "详情",
    "全文",
    "摘要",
    "报道",
    "据悉",
    "ai",
    "llm",
}

# Extra domain phrases beyond category aliases (longer first).
_EXTRA_LEXICON = (
    "physics-informed",
    "physics informed",
    "neural network",
    "transformer",
    "diffusion",
    "reinforcement learning",
    "context window",
    "tool calling",
    "function calling",
    "structured output",
    "json schema",
    "open source",
    "github",
    "huggingface",
    "arxiv",
    "deepseek",
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "qwen",
    "llama",
    "pytorch",
    "tensorflow",
    "langchain",
    "llamaindex",
    "vector database",
    "embedding",
    "fine-tuning",
    "finetune",
    "quantization",
    "benchmark",
    "leaderboard",
    "agent",
    "rag",
    "多模态",
    "大模型",
    "大语言模型",
    "智能体",
    "检索增强",
    "向量数据库",
    "微调",
    "量化",
    "评测",
    "基准",
    "具身智能",
    "机器人",
    "插件",
    "源码",
    "架构图",
    "验收",
    "流水线",
    "知识库",
    "提示词",
    "上下文",
)

_RELATED_STATUSES = (
    ItemStatus.CANDIDATE,
    ItemStatus.SELECTED,
    ItemStatus.SUMMARIZED,
    ItemStatus.PUBLISHED,
)

# Need enough shared core keywords to claim “摘要关键词相近”.
_MIN_SHARED_KEYWORDS = 2
_KEYWORD_JACCARD_MIN = 0.12


def _build_lexicon() -> list[str]:
    phrases: list[str] = []
    for _, aliases in _ALIAS_GROUPS:
        phrases.extend(aliases)
    phrases.extend(_EXTRA_LEXICON)
    # Longer phrases first so "large language model" wins over "model".
    uniq = sorted({p.lower().strip() for p in phrases if p and p.strip()}, key=len, reverse=True)
    # Drop ultra-short / stop lexicon entries that create false matches.
    return [p for p in uniq if len(p) >= 3 and p not in _STOP]


_LEXICON = _build_lexicon()


@dataclass
class RelatedHit:
    item: IntelItem
    score: float
    reasons: list[str] = field(default_factory=list)
    keyword_sim: float = 0.0


@dataclass
class RelatedBundle:
    seed: IntelItem
    groups: list[tuple[str, list[RelatedHit]]]
    total: int


def _norm(text: str | None) -> str:
    return strip_html(text).lower().strip()


def _author_parts(author: str | None) -> set[str]:
    if not author:
        return set()
    parts = _AUTHOR_SPLIT.split(author)
    return {p.strip().lower() for p in parts if len(p.strip()) >= 2}


def _github_owner(item: IntelItem) -> str:
    meta = item.metadata_ or {}
    full = str(meta.get("repo_full_name") or "")
    if "/" in full:
        return full.split("/", 1)[0].lower()
    return _norm(item.author)


def _summary_text(item: IntelItem) -> str:
    """Prefer摘要; fall back to content then title."""
    parts = [
        getattr(item, "llm_summary", None) or "",
        item.summary or "",
        item.content or "",
    ]
    body = strip_html(" ".join(p for p in parts if p))
    if len(body) >= 24:
        return body
    title = strip_html(item.title or "")
    return f"{body} {title}".strip()


def extract_core_keywords(text: str | None, *, limit: int = 28) -> set[str]:
    """Pull core keywords from summary text for similarity matching."""
    raw = _norm(text)
    if not raw:
        return set()

    found: dict[str, float] = {}
    covered = [False] * len(raw)

    def _mark(start: int, end: int) -> None:
        for i in range(start, min(end, len(covered))):
            covered[i] = True

    # 1) Known domain phrases (highest confidence).
    for phrase in _LEXICON:
        start = 0
        while True:
            idx = raw.find(phrase, start)
            if idx < 0:
                break
            end = idx + len(phrase)
            if not any(covered[idx:end]):
                found[phrase] = found.get(phrase, 0.0) + 3.0 + min(2.0, len(phrase) / 8)
                _mark(idx, end)
            start = idx + 1

    # 2) English / product tokens on uncovered spans.
    for m in _EN_TOKEN.finditer(raw):
        w = m.group().lower().strip("-")
        if w in _STOP or w.isdigit() or len(w) < 3:
            continue
        if any(covered[m.start() : m.end()]):
            continue
        found[w] = found.get(w, 0.0) + 1.6 + min(1.2, len(w) / 10)
        _mark(m.start(), m.end())

    # 3) Chinese leftover: prefer 3–4 char grams (more specific than bigrams).
    chars = [(i, c) for i, c in enumerate(raw) if "\u4e00" <= c <= "\u9fff" and not covered[i]]
    # Stitch contiguous uncovered Chinese runs.
    runs: list[str] = []
    buf: list[str] = []
    prev_i = -2
    for i, c in chars:
        if i == prev_i + 1:
            buf.append(c)
        else:
            if buf:
                runs.append("".join(buf))
            buf = [c]
        prev_i = i
    if buf:
        runs.append("".join(buf))

    for run in runs:
        if len(run) < 3:
            continue
        # Slide 4-grams then 3-grams; keep a few per run.
        local: list[tuple[float, str]] = []
        for n in (4, 3):
            if len(run) < n:
                continue
            for i in range(0, len(run) - n + 1, max(1, n // 2)):
                gram = run[i : i + n]
                if gram in _STOP:
                    continue
                local.append((float(n), gram))
        local.sort(reverse=True)
        seen_local: set[str] = set()
        for score, gram in local:
            if gram in seen_local:
                continue
            seen_local.add(gram)
            found[gram] = found.get(gram, 0.0) + score
            if len(seen_local) >= 6:
                break

    if not found:
        return set()

    ranked = sorted(found.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    return {k for k, _ in ranked[:limit]}


def keyword_similarity(keys_a: set[str], keys_b: set[str]) -> tuple[float, set[str]]:
    if not keys_a or not keys_b:
        return 0.0, set()
    shared = keys_a & keys_b
    if not shared:
        return 0.0, set()
    jac = len(shared) / len(keys_a | keys_b)
    # Reward multiple strong overlaps.
    strong = {k for k in shared if len(k) >= 4 or " " in k or "-" in k}
    bonus = 0.06 * min(3, len(strong))
    return min(1.0, jac + bonus), shared


def _same_type_family(item_type: str) -> list[str]:
    if item_type in {ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE}:
        return [ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE]
    return [item_type]


def _pool_for(
    session: Session,
    seed: IntelItem,
    *,
    limit: int = 360,
    cross_type: bool = False,
) -> list[IntelItem]:
    if cross_type:
        types = [
            ItemType.NEWS,
            ItemType.PAPER,
            ItemType.MODEL,
            ItemType.STOCK_NEWS,
            ItemType.EDUCATION,
            ItemType.GITHUB_REPO,
            ItemType.GITHUB_RELEASE,
            ItemType.MEDIA_POST,
            ItemType.WECHAT_MSG,
        ]
    else:
        types = _same_type_family(seed.item_type)
    stmt = (
        select(IntelItem)
        .where(
            IntelItem.status.in_(_RELATED_STATUSES),
            IntelItem.item_type.in_(types),
            IntelItem.id != seed.id,
        )
        .order_by(
            IntelItem.score.desc(),
            func.coalesce(IntelItem.published_at, IntelItem.first_seen_at).desc(),
        )
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def _same_author(seed: IntelItem, other: IntelItem) -> bool:
    itype = seed.item_type
    if itype in {ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE}:
        so, oo = _github_owner(seed), _github_owner(other)
        return bool(so and oo and so == oo)
    sa, oa = _author_parts(seed.author), _author_parts(other.author)
    return bool(sa and oa and (sa & oa))


def _shared_label(shared: set[str], *, limit: int = 5) -> str:
    ranked = sorted(shared, key=lambda x: (-len(x), x))[:limit]
    return "、".join(ranked)


def _score_pair(
    seed: IntelItem,
    other: IntelItem,
    *,
    seed_keys: set[str],
) -> RelatedHit | None:
    other_keys = extract_core_keywords(_summary_text(other))
    sim, shared = keyword_similarity(seed_keys, other_keys)
    author_hit = _same_author(seed, other)
    reasons: list[str] = []
    score = 0.0

    keyword_hit = len(shared) >= _MIN_SHARED_KEYWORDS and sim >= _KEYWORD_JACCARD_MIN
    # One very strong phrase (e.g. product/tech name) can also qualify.
    if not keyword_hit and len(shared) == 1:
        only = next(iter(shared))
        if len(only) >= 6 or " " in only:
            keyword_hit = True
            sim = max(sim, 0.18)

    if author_hit:
        score += 5.5
        if seed.item_type in {ItemType.GITHUB_REPO, ItemType.GITHUB_RELEASE}:
            reasons.append("同一作者/组织")
        else:
            reasons.append("同一作者")

    if keyword_hit:
        score += 12.0 * sim + 1.5 * min(4, len(shared))
        reasons.append(f"摘要关键词 · {_shared_label(shared)}")
    elif author_hit:
        score += 1.0
    else:
        return None

    score += min(0.6, float(other.score or 0) * 0.02)

    if score < 3.0 or not reasons:
        return None

    seen: set[str] = set()
    uniq: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            uniq.append(r)

    return RelatedHit(
        item=other,
        score=round(score, 3),
        reasons=uniq,
        keyword_sim=round(sim, 3),
    )


def _group_hits(hits: list[RelatedHit]) -> list[tuple[str, list[RelatedHit]]]:
    authors: list[RelatedHit] = []
    keywords: list[RelatedHit] = []
    used: set[UUID] = set()

    for h in hits:
        if h.item.id in used:
            continue
        used.add(h.item.id)
        rs = " ".join(h.reasons)
        if "摘要关键词" in rs:
            keywords.append(h)
        elif "同一作者" in rs or "同一作者/组织" in rs:
            authors.append(h)

    out: list[tuple[str, list[RelatedHit]]] = []
    if keywords:
        keywords.sort(key=lambda x: (x.keyword_sim, x.score), reverse=True)
        out.append(("摘要关键词相近", keywords))
    if authors:
        authors.sort(key=lambda x: x.score, reverse=True)
        out.append(("同一作者（其他作品）", authors))
    return out


def find_related(
    session: Session,
    item_id: UUID,
    *,
    limit: int = 20,
    cross_type: bool = False,
) -> RelatedBundle:
    seed = ItemRepository(session).get(item_id)
    if seed is None:
        raise LookupError("条目不存在")

    seed_keys = extract_core_keywords(_summary_text(seed))
    pool = _pool_for(session, seed, cross_type=cross_type)
    scored: list[RelatedHit] = []
    for other in pool:
        hit = _score_pair(seed, other, seed_keys=seed_keys)
        if hit:
            scored.append(hit)
    scored.sort(key=lambda h: (h.keyword_sim, h.score), reverse=True)
    top = scored[:limit]
    return RelatedBundle(seed=seed, groups=_group_hits(top), total=len(top))


def find_related_drawer(session: Session, item_id: UUID, *, limit: int = 36) -> dict:
    """Payload for side-drawer: type-grouped list + ECharts subgraph."""
    from bagel.services.gbrain import item_subgraph
    from bagel.web.templating import present_item

    _TYPE_LABELS = {
        ItemType.NEWS: "新闻",
        ItemType.PAPER: "论文",
        ItemType.MODEL: "模型",
        ItemType.STOCK_NEWS: "股票",
        ItemType.EDUCATION: "教育",
        ItemType.GITHUB_REPO: "GitHub 项目",
        ItemType.GITHUB_RELEASE: "GitHub Release",
        ItemType.MEDIA_POST: "自媒体",
        ItemType.WECHAT_MSG: "微信",
    }

    bundle = find_related(session, item_id, limit=limit, cross_type=True)
    seed = bundle.seed
    flat: list[RelatedHit] = []
    for _title, hits in bundle.groups:
        flat.extend(hits)

    by_type: dict[str, list] = {}
    for hit in flat:
        label = _TYPE_LABELS.get(hit.item.item_type, hit.item.item_type)
        by_type.setdefault(label, []).append(
            {
                "score": hit.score,
                "reasons": hit.reasons,
                "item": present_item(hit.item, preview=False),
            }
        )
    type_groups = [
        {"type_label": k, "count": len(v), "hits": v}
        for k, v in sorted(by_type.items(), key=lambda x: -len(x[1]))
    ]
    echarts = item_subgraph(session, seed, [h.item for h in flat])
    return {
        "seed": present_item(seed, preview=False),
        "type_label": _TYPE_LABELS.get(seed.item_type, seed.item_type),
        "type_groups": type_groups,
        "total": bundle.total,
        "echarts": echarts,
        "full_url": f"/briefs/space?seed={seed.id}",
    }


def supports_related(item_type: str | None) -> bool:
    return item_type in {
        ItemType.NEWS,
        ItemType.PAPER,
        ItemType.STOCK_NEWS,
        ItemType.GITHUB_REPO,
        ItemType.GITHUB_RELEASE,
        ItemType.MEDIA_POST,
        ItemType.MODEL,
        ItemType.EDUCATION,
    }


# Back-compat alias used by older tests / callers.
def title_similarity(a: str | None, b: str | None) -> tuple[float, set[str]]:
    return keyword_similarity(extract_core_keywords(a), extract_core_keywords(b))
