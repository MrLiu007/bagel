"""Seed default sources, keyword rules, and GitHub queries on empty DBs.

Idempotent: only inserts when the corresponding table has zero rows.
Catalog of default news URLs is mirrored in `docs/default-news-sources.md`.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bagel.domain.enums import KeywordRuleType, NetworkRequirement, Region, SourceType
from bagel.domain.models import IntelGithubQuery, IntelKeywordRule, IntelSource

# 20+ stable AI news / blog sources (official RSS preferred)
DEFAULT_SOURCES: list[dict] = [
    # --- CN ---
    {"name": "机器之心", "url": "https://www.jiqizhixin.com/rss", "region": Region.CN, "priority": 10},
    {"name": "量子位", "url": "https://www.qbitai.com/feed", "region": Region.CN, "priority": 20},
    {"name": "InfoQ 中国", "url": "https://www.infoq.cn/feed", "region": Region.CN, "priority": 30},
    {"name": "少数派", "url": "https://sspai.com/feed", "region": Region.CN, "priority": 40},
    {"name": "Solidot", "url": "https://www.solidot.org/index.rss", "region": Region.CN, "priority": 50},
    {"name": "36氪", "url": "https://36kr.com/feed", "region": Region.CN, "priority": 60},
    {"name": "IT之家", "url": "https://www.ithome.com/rss/", "region": Region.CN, "priority": 70},
    {"name": "OSCHINA", "url": "https://www.oschina.net/news/rss", "region": Region.CN, "priority": 80},
    {"name": "掘金后端", "url": "https://juejin.cn/rss", "region": Region.CN, "priority": 90},
    {"name": "博客园精华", "url": "https://www.cnblogs.com/aggsite/rss", "region": Region.CN, "priority": 100},
    # --- GLOBAL ---
    {"name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 10},
    {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 20},
    {"name": "DeepMind", "url": "https://deepmind.google/blog/rss.xml", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 30},
    {"name": "Anthropic", "url": "https://raw.githubusercontent.com/anthropics/anthropic-cookbook/main/README.md", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 40, "enabled": False},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 50},
    {"name": "Meta AI", "url": "https://ai.meta.com/blog/rss/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 60},
    {"name": "NVIDIA Blog", "url": "https://blogs.nvidia.com/feed/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 70},
    {"name": "Microsoft Research", "url": "https://www.microsoft.com/en-us/research/feed/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 80},
    {"name": "AWS ML Blog", "url": "https://aws.amazon.com/blogs/machine-learning/feed/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 90},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 100},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 110},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/technology-lab", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 120},
    {"name": "Towards Data Science", "url": "https://towardsdatascience.com/feed", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 130},
    {"name": "PyTorch Blog", "url": "https://pytorch.org/blog/feed.xml", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 140},
    {"name": "LangChain Blog", "url": "https://blog.langchain.dev/rss/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 150},
    # --- Reddit (official .rss; require browser-like UA — see http.fetch_text) ---
    {
        "name": "Reddit r/MachineLearning",
        "url": "https://www.reddit.com/r/MachineLearning/new/.rss",
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 160,
    },
    {
        "name": "Reddit r/LocalLLaMA",
        "url": "https://www.reddit.com/r/LocalLLaMA/new/.rss",
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 170,
    },
    {
        "name": "Reddit r/artificial",
        "url": "https://www.reddit.com/r/artificial/new/.rss",
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 180,
    },
    {
        "name": "Reddit r/LanguageTechnology",
        "url": "https://www.reddit.com/r/LanguageTechnology/new/.rss",
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 190,
    },
    # RSSHub adapters (paths resolved against RSSHUB_BASE_URL)
    {"name": "微博热搜 (RSSHub)", "url": "/weibo/search/hot", "region": Region.CN, "source_type": SourceType.RSSHUB, "priority": 200, "enabled": False},
    {"name": "GitHub Trending (RSSHub)", "url": "/github/trending/daily/python", "region": Region.GLOBAL, "source_type": SourceType.RSSHUB, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 210, "enabled": False},
    {"name": "Reddit via RSSHub (备用)", "url": "/reddit/user/username/submitted", "region": Region.GLOBAL, "source_type": SourceType.RSSHUB, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 220, "enabled": False},
]

# Reddit rows also used by ensure_reddit_sources for existing DBs
DEFAULT_REDDIT_SOURCES: list[dict] = [
    row for row in DEFAULT_SOURCES if "reddit.com" in str(row.get("url", "")).lower()
]


DEFAULT_PAPER_SOURCES: list[dict] = [
    {"name": "arXiv cs.AI", "url": "arxiv:cs.AI", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 10},
    {"name": "arXiv cs.LG", "url": "arxiv:cs.LG", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 20},
    {"name": "arXiv cs.CL", "url": "arxiv:cs.CL", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 30},
    {"name": "arXiv cs.CV", "url": "arxiv:cs.CV", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 40},
    {"name": "arXiv cs.RO", "url": "arxiv:cs.RO", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 50},
    {"name": "Hugging Face Papers", "url": "hf:daily", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 60},
    {"name": "OpenAlex AI", "url": "openalex:C154945302", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 70},
    {"name": "Semantic Scholar LLM", "url": "s2:large language model", "source_type": SourceType.PAPER, "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 80},
]

# Stock / market news RSS (STOCK type). Relative paths resolve via RSSHub.
DEFAULT_STOCK_SOURCES: list[dict] = [
    # --- GLOBAL ---
    {
        "name": "Yahoo Finance",
        "url": "https://finance.yahoo.com/news/rssindex",
        "source_type": SourceType.STOCK,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 10,
    },
    {
        "name": "MarketWatch Top Stories",
        "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "source_type": SourceType.STOCK,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 20,
    },
    {
        "name": "CNBC Top News",
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
        "source_type": SourceType.STOCK,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 30,
    },
    {
        "name": "BBC Business",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "source_type": SourceType.STOCK,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 40,
    },
    {
        "name": "Investing.com Markets",
        "url": "https://www.investing.com/rss/news_25.rss",
        "source_type": SourceType.STOCK,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 50,
    },
    # --- CN (RSSHub adapters — enable after RSSHub is reachable) ---
    {
        "name": "财联社电报 (RSSHub)",
        "url": "/cls/telegraph",
        "source_type": SourceType.STOCK,
        "region": Region.CN,
        "network": NetworkRequirement.DIRECT,
        "priority": 10,
        "enabled": False,
    },
    {
        "name": "东方财富财经导读 (RSSHub)",
        "url": "/eastmoney/report/strategyreport",
        "source_type": SourceType.STOCK,
        "region": Region.CN,
        "network": NetworkRequirement.DIRECT,
        "priority": 20,
        "enabled": False,
    },
    {
        "name": "华尔街见闻最热 (RSSHub)",
        "url": "/wallstreetcn/hot",
        "source_type": SourceType.STOCK,
        "region": Region.CN,
        "network": NetworkRequirement.DIRECT,
        "priority": 30,
        "enabled": False,
    },
]

DEFAULT_KEYWORDS: list[tuple[str, str, float]] = [
    ("AI Agent", KeywordRuleType.INCLUDE, 2.0),
    ("RAG", KeywordRuleType.INCLUDE, 2.0),
    ("GraphRAG", KeywordRuleType.BOOST, 2.5),
    ("multimodal", KeywordRuleType.INCLUDE, 1.5),
    ("reasoning", KeywordRuleType.INCLUDE, 1.5),
    ("robotics", KeywordRuleType.INCLUDE, 1.5),
    ("embodied AI", KeywordRuleType.INCLUDE, 2.0),
    ("AI education", KeywordRuleType.INCLUDE, 1.5),
    ("benchmark", KeywordRuleType.BOOST, 1.2),
    ("release", KeywordRuleType.BOOST, 1.2),
    ("开源", KeywordRuleType.INCLUDE, 1.5),
    ("大模型", KeywordRuleType.INCLUDE, 2.0),
    ("大语言模型", KeywordRuleType.INCLUDE, 2.0),
    ("LLM", KeywordRuleType.INCLUDE, 2.0),
    ("GPT", KeywordRuleType.INCLUDE, 1.5),
    ("训练", KeywordRuleType.BOOST, 1.0),
    ("推理", KeywordRuleType.BOOST, 1.0),
    ("Agent", KeywordRuleType.INCLUDE, 1.8),
    ("培训招生", KeywordRuleType.EXCLUDE, 0.0),
    ("荐股", KeywordRuleType.EXCLUDE, 0.0),
    ("付费课程", KeywordRuleType.EXCLUDE, 0.0),
    ("娱乐八卦", KeywordRuleType.EXCLUDE, 0.0),
]

DEFAULT_GITHUB_QUERIES: list[tuple[str, str]] = [
    ("LLM", "llm OR \"large language model\" in:name,description,topics stars:>50"),
    ("Multimodal", "multimodal OR vision-language in:name,description,topics stars:>30"),
    ("Agent", "\"ai agent\" OR langchain OR autogen OR crewai stars:>50"),
    ("RAG", "RAG OR \"retrieval augmented\" OR graphrag stars:>30"),
    ("GraphRAG", "graphrag OR \"graph rag\" stars:>10"),
    ("Inference", "vllm OR \"llm inference\" OR tensorrt-llm stars:>50"),
    ("Fine-tuning", "finetune OR \"fine-tuning\" OR lora OR qlora stars:>50"),
    ("Quantization", "quantization OR gguf OR awq OR gptq stars:>30"),
    ("AI Data", "\"synthetic data\" OR dataset llm OR \"instruction data\" stars:>30"),
    ("AI Evaluation", "\"llm eval\" OR benchmark OR lm-eval stars:>30"),
    ("Robotics", "robotics OR ros2 AI OR \"robot learning\" stars:>30"),
    ("Embodied AI", "\"embodied ai\" OR \"vision language action\" OR vla stars:>10"),
    ("AI Education", "\"ai education\" OR \"llm tutor\" OR \"edu agent\" stars:>10"),
]


def seed_if_empty(session: Session) -> dict[str, int]:
    """Idempotent seed of business config tables."""
    from bagel.services.auth import ensure_default_admin

    created = {
        "sources": 0,
        "keywords": 0,
        "github_queries": 0,
        "paper_sources": 0,
        "stock_sources": 0,
        "users": 0,
    }
    admin = ensure_default_admin(session)
    created["users"] = 1 if admin is not None else 0
    # Attach legacy rows without owner to default admin for isolation baseline.
    if admin is not None:
        from bagel.domain.models import IntelItem
        from sqlalchemy import update

        session.execute(
            update(IntelItem)
            .where(IntelItem.owner_id.is_(None))
            .values(owner_id=admin.id)
        )

    source_count = session.scalar(select(func.count()).select_from(IntelSource)) or 0
    if source_count == 0:
        for row in DEFAULT_SOURCES:
            session.add(
                IntelSource(
                    name=row["name"],
                    url=row["url"],
                    source_type=row.get("source_type", SourceType.RSS),
                    region=row.get("region", Region.CN),
                    network_requirement=row.get("network", NetworkRequirement.DIRECT),
                    priority=row.get("priority", 100),
                    enabled=row.get("enabled", True),
                )
            )
            created["sources"] += 1

    kw_count = session.scalar(select(func.count()).select_from(IntelKeywordRule)) or 0
    if kw_count == 0:
        for keyword, rule_type, weight in DEFAULT_KEYWORDS:
            session.add(
                IntelKeywordRule(keyword=keyword, rule_type=rule_type, weight=weight, enabled=True)
            )
            created["keywords"] += 1

    gq_count = session.scalar(select(func.count()).select_from(IntelGithubQuery)) or 0
    if gq_count == 0:
        for name, query in DEFAULT_GITHUB_QUERIES:
            session.add(IntelGithubQuery(name=name, query=query, enabled=True))
            created["github_queries"] += 1

    paper_count = session.scalar(
        select(func.count()).select_from(IntelSource).where(IntelSource.source_type == SourceType.PAPER)
    ) or 0
    if paper_count == 0:
        for row in DEFAULT_PAPER_SOURCES:
            session.add(
                IntelSource(
                    name=row["name"],
                    url=row["url"],
                    source_type=row.get("source_type", SourceType.PAPER),
                    region=row.get("region", Region.GLOBAL),
                    network_requirement=row.get("network", NetworkRequirement.PROXY_PREFERRED),
                    priority=row.get("priority", 100),
                    enabled=row.get("enabled", True),
                )
            )
            created["paper_sources"] = created.get("paper_sources", 0) + 1

    stock_count = session.scalar(
        select(func.count()).select_from(IntelSource).where(IntelSource.source_type == SourceType.STOCK)
    ) or 0
    if stock_count == 0:
        for row in DEFAULT_STOCK_SOURCES:
            session.add(
                IntelSource(
                    name=row["name"],
                    url=row["url"],
                    source_type=row.get("source_type", SourceType.STOCK),
                    region=row.get("region", Region.GLOBAL),
                    network_requirement=row.get("network", NetworkRequirement.PROXY_PREFERRED),
                    priority=row.get("priority", 100),
                    enabled=row.get("enabled", True),
                )
            )
            created["stock_sources"] += 1

    created["reddit_sources"] = ensure_reddit_sources(session)

    session.flush()
    return created


def ensure_reddit_sources(session: Session) -> int:
    """Add missing Reddit RSS sources even when the news source table is non-empty."""
    existing_urls = {
        (u or "").strip().lower()
        for u in session.scalars(select(IntelSource.url)).all()
    }
    added = 0
    for row in DEFAULT_REDDIT_SOURCES:
        url = str(row["url"]).strip()
        if url.lower() in existing_urls:
            continue
        session.add(
            IntelSource(
                name=row["name"],
                url=url,
                source_type=row.get("source_type", SourceType.RSS),
                region=row.get("region", Region.GLOBAL),
                network_requirement=row.get("network", NetworkRequirement.PROXY_PREFERRED),
                priority=row.get("priority", 160),
                enabled=row.get("enabled", True),
            )
        )
        existing_urls.add(url.lower())
        added += 1
    if added:
        session.flush()
    return added
