"""Seed default sources, keyword rules, and GitHub queries on empty DBs.

Idempotent: only inserts when the corresponding table has zero rows.
Catalog of default news URLs is mirrored in `docs/default-news-sources.md`.
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemType, KeywordRuleType, NetworkRequirement, Region, SourceType
from bagel.domain.models import IntelGithubQuery, IntelItem, IntelKeywordRule, IntelSource

# 20+ stable AI news / blog sources (official RSS preferred)
# X (Twitter) via RSSHub — defined first so DEFAULT_SOURCES can include them.
DEFAULT_X_SOURCES: list[dict] = [
    {
        "name": "X · OpenAI",
        "url": "/twitter/user/OpenAI",
        "region": Region.GLOBAL,
        "source_type": SourceType.RSSHUB,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 230,
        # RSSHub→X often 502 without cookies / healthy RSSHub; opt-in in settings.
        "enabled": False,
    },
    {
        "name": "X · Anthropic",
        "url": "/twitter/user/AnthropicAI",
        "region": Region.GLOBAL,
        "source_type": SourceType.RSSHUB,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 240,
        "enabled": False,
    },
    {
        "name": "X · Hugging Face",
        "url": "/twitter/user/HuggingFace",
        "region": Region.GLOBAL,
        "source_type": SourceType.RSSHUB,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 250,
        "enabled": False,
    },
    {
        "name": "X · Andrej Karpathy",
        "url": "/twitter/user/karpathy",
        "region": Region.GLOBAL,
        "source_type": SourceType.RSSHUB,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 260,
        "enabled": False,
    },
    {
        "name": "X · Andrew Ng",
        "url": "/twitter/user/AndrewYNg",
        "region": Region.GLOBAL,
        "source_type": SourceType.RSSHUB,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 270,
        "enabled": False,
    },
    {
        "name": "X · DeepLearningAI",
        "url": "/twitter/user/DeepLearningAI",
        "region": Region.GLOBAL,
        "source_type": SourceType.RSSHUB,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 280,
        "enabled": False,
    },
]

DEFAULT_SOURCES: list[dict] = [
    # --- CN ---
    {
        "name": "机器之心",
        "url": "https://www.jiqizhixin.com/rss",
        "region": Region.CN,
        "priority": 10,
        "enabled": False,  # official page is HTML/paywalled, not a public RSS body
    },
    {
        "name": "量子位",
        "url": "https://www.qbitai.com/feed",
        "region": Region.CN,
        "priority": 20,
        "enabled": False,  # often 403 without residential IP
    },
    {"name": "InfoQ 中国", "url": "https://www.infoq.cn/feed", "region": Region.CN, "priority": 30},
    {"name": "少数派", "url": "https://sspai.com/feed", "region": Region.CN, "priority": 40},
    {"name": "Solidot", "url": "https://www.solidot.org/index.rss", "region": Region.CN, "priority": 50},
    {"name": "36氪", "url": "https://36kr.com/feed", "region": Region.CN, "priority": 60},
    {"name": "IT之家", "url": "https://www.ithome.com/rss/", "region": Region.CN, "priority": 70},
    {"name": "OSCHINA", "url": "https://www.oschina.net/news/rss", "region": Region.CN, "priority": 80},
    {"name": "掘金后端", "url": "https://juejin.cn/rss", "region": Region.CN, "priority": 90},
    {
        "name": "博客园精华",
        "url": "https://feed.cnblogs.com/blog/sitehome/rss",
        "region": Region.CN,
        "priority": 100,
    },
    {"name": "爱范儿", "url": "https://www.ifanr.com/feed", "region": Region.CN, "priority": 105},
    # --- GLOBAL ---
    {"name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 10},
    {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 20},
    {"name": "DeepMind", "url": "https://deepmind.google/blog/rss.xml", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 30},
    {"name": "Anthropic", "url": "https://raw.githubusercontent.com/anthropics/anthropic-cookbook/main/README.md", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 40, "enabled": False},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 50},
    {
        "name": "Meta Engineering",
        "url": "https://engineering.fb.com/feed/",
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 60,
    },
    {"name": "NVIDIA Blog", "url": "https://blogs.nvidia.com/feed/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 70},
    {"name": "Microsoft Research", "url": "https://www.microsoft.com/en-us/research/feed/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 80},
    {"name": "AWS ML Blog", "url": "https://aws.amazon.com/blogs/machine-learning/feed/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 90},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 100},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 110},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/technology-lab", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 120},
    {"name": "Towards Data Science", "url": "https://towardsdatascience.com/feed", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 130},
    {"name": "PyTorch Blog", "url": "https://pytorch.org/blog/feed.xml", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 140},
    {
        "name": "LangChain Blog",
        "url": "https://blog.langchain.dev/rss.xml",
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 150,
    },
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
    # --- X (Twitter) via RSSHub — needs RSSHUB_BASE_URL; overseas may need proxy; failures skip ---
    *DEFAULT_X_SOURCES,
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
    {
        "name": "Semantic Scholar LLM",
        "url": "s2:large language model",
        "source_type": SourceType.PAPER,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 80,
        # Anonymous S2 search often hits 429; enable after SEMANTIC_SCHOLAR_API_KEY.
        "enabled": False,
    },
]

# AI model hubs (MODEL type). Keep the enabled set small — overlapping feeds
# (recent + downloads + pipeline) produce near-duplicate model lists.
DEFAULT_MODEL_SOURCES: list[dict] = [
    {
        "name": "Hugging Face",
        "url": "hf:models",
        "source_type": SourceType.MODEL,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 10,
    },
    {
        "name": "ModelScope 魔搭",
        "url": "ms:models",
        "source_type": SourceType.MODEL,
        "region": Region.CN,
        "network": NetworkRequirement.DIRECT,
        "priority": 20,
    },
]

DEFAULT_EDUCATION_SOURCES: list[dict] = [
    # --- MIT ---
    {
        "name": "MIT OCW · New Courses",
        "url": "https://old.ocw.mit.edu/rss/new/mit-newcourses.xml",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 10,
    },
    {
        "name": "MIT News · AI",
        "url": "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 15,
    },
    {
        "name": "MIT News",
        "url": "https://news.mit.edu/rss/feed",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 18,
        "enabled": False,  # broad campus news; enable if you want full MIT feed
    },
    # --- Stanford / Berkeley / Harvard / Yale ---
    {
        "name": "Stanford AI Lab Blog",
        "url": "https://ai.stanford.edu/blog/feed.xml",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 20,
    },
    {
        "name": "UC Berkeley News",
        "url": "https://news.berkeley.edu/feed/",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 25,
    },
    {
        "name": "Harvard Gazette",
        "url": "https://news.harvard.edu/gazette/feed/",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 28,
    },
    {
        "name": "Yale Open Courses",
        "url": "https://oyc.yale.edu/rss.xml",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 30,
    },
    # --- Platforms / open learning ---
    {
        "name": "Class Central",
        "url": "https://www.classcentral.com/report/feed/",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 40,
    },
    {
        "name": "Coursera Blog",
        "url": "https://blog.coursera.org/feed/",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 45,
    },
    {
        "name": "Khan Academy Blog",
        "url": "https://blog.khanacademy.org/feed/",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 50,
    },
    {
        "name": "CMU Open Learning Initiative",
        "url": "https://oli.cmu.edu/feed/",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 55,
    },
    {
        "name": "fast.ai",
        "url": "https://www.fast.ai/index.xml",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 60,
    },
    {
        "name": "Distill",
        "url": "https://distill.pub/rss.xml",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 65,
    },
    {
        "name": "Lil'Log（教学向 ML 笔记）",
        "url": "https://lilianweng.github.io/index.xml",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 70,
    },
    # --- CN via RSSHub (optional; need RSSHUB_BASE_URL) ---
    {
        "name": "清华 · 学堂在线（RSSHub）",
        "url": "/xuetangx/courses",
        "source_type": SourceType.EDUCATION,
        "region": Region.CN,
        "network": NetworkRequirement.DIRECT,
        "priority": 80,
        "enabled": False,
    },
    {
        "name": "北大开放课程（RSSHub）",
        "url": "/universities/pku/opencourse",
        "source_type": SourceType.EDUCATION,
        "region": Region.CN,
        "network": NetworkRequirement.DIRECT,
        "priority": 85,
        "enabled": False,
    },
]

# Broken / obsolete education feed URLs → replacement URL (or "" to disable).
_EDUCATION_URL_MIGRATIONS: dict[str, str] = {
    "https://ocw.mit.edu/rss/new/mit-allcourses.xml": (
        "https://old.ocw.mit.edu/rss/new/mit-newcourses.xml"
    ),
    "https://ocw.mit.edu/rss/new/mit-newcourses.xml": (
        "https://old.ocw.mit.edu/rss/new/mit-newcourses.xml"
    ),
    "https://online.stanford.edu/news/rss.xml": "https://ai.stanford.edu/blog/feed.xml",
    "https://news.stanford.edu/feed": "https://ai.stanford.edu/blog/feed.xml",
    "https://news.stanford.edu/feed/": "https://ai.stanford.edu/blog/feed.xml",
    "https://blog.edx.org/feed": "",  # often returns HTML shell with 0 entries
    "https://www.harvardonline.harvard.edu/blog/rss.xml": (
        "https://news.harvard.edu/gazette/feed/"
    ),
}

_EDUCATION_NAME_FIXES: dict[str, str] = {
    "https://old.ocw.mit.edu/rss/new/mit-newcourses.xml": "MIT OCW · New Courses",
    "https://ai.stanford.edu/blog/feed.xml": "Stanford AI Lab Blog",
    "https://news.harvard.edu/gazette/feed/": "Harvard Gazette",
}

# Broken / obsolete news RSS URLs → replacement ("" disables).
_NEWS_URL_MIGRATIONS: dict[str, str] = {
    "https://www.cnblogs.com/aggsite/rss": "https://feed.cnblogs.com/blog/sitehome/rss",
    "https://blog.langchain.dev/rss/": "https://blog.langchain.dev/rss.xml",
    "https://blog.langchain.dev/rss": "https://blog.langchain.dev/rss.xml",
    "https://ai.meta.com/blog/rss/": "https://engineering.fb.com/feed/",
    "https://ai.meta.com/blog/rss": "https://engineering.fb.com/feed/",
}

_NEWS_DISABLE_URLS: frozenset[str] = frozenset(
    {
        "https://www.jiqizhixin.com/rss",
        "https://www.qbitai.com/feed",
    }
)

_NEWS_NAME_FIXES: dict[str, str] = {
    "https://feed.cnblogs.com/blog/sitehome/rss": "博客园精华",
    "https://blog.langchain.dev/rss.xml": "LangChain Blog",
    "https://engineering.fb.com/feed/": "Meta Engineering",
}

# Added to existing DBs that were seeded before these feeds existed.
_NEWS_ENSURE_EXTRA: list[dict] = [
    {
        "name": "爱范儿",
        "url": "https://www.ifanr.com/feed",
        "region": Region.CN,
        "priority": 105,
    },
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

DEFAULT_KEYWORDS: list[tuple[str, str, float, str]] = [
    # INCLUDE — news-scoped defaults; semantically near-duplicates removed
    # (dropped: AI Agent≈Agent, 大语言模型≈大模型, GPT≈LLM).
    ("Agent", KeywordRuleType.INCLUDE, 2.0, "news"),
    ("RAG", KeywordRuleType.INCLUDE, 2.0, "news"),
    ("LLM", KeywordRuleType.INCLUDE, 2.0, "news"),
    ("大模型", KeywordRuleType.INCLUDE, 2.0, "news"),
    ("multimodal", KeywordRuleType.INCLUDE, 1.5, "news"),
    ("reasoning", KeywordRuleType.INCLUDE, 1.5, "news"),
    ("robotics", KeywordRuleType.INCLUDE, 1.5, "news"),
    ("embodied AI", KeywordRuleType.INCLUDE, 2.0, "news"),
    ("AI education", KeywordRuleType.INCLUDE, 1.5, "news"),
    ("开源", KeywordRuleType.INCLUDE, 1.5, "news"),
    # BOOST — score only
    ("GraphRAG", KeywordRuleType.BOOST, 2.5, "news,github,papers,models"),
    ("benchmark", KeywordRuleType.BOOST, 1.2, "news,github,papers,models"),
    ("release", KeywordRuleType.BOOST, 1.2, "news,github"),
    ("训练", KeywordRuleType.BOOST, 1.0, "news,papers,models"),
    ("推理", KeywordRuleType.BOOST, 1.0, "news,papers,models"),
    # EXCLUDE — all resource categories by default
    (
        "培训招生",
        KeywordRuleType.EXCLUDE,
        0.0,
        "news,github,stocks,papers,models,education,media,wechat",
    ),
    (
        "荐股",
        KeywordRuleType.EXCLUDE,
        0.0,
        "news,github,stocks,papers,models,education,media,wechat",
    ),
    (
        "付费课程",
        KeywordRuleType.EXCLUDE,
        0.0,
        "news,github,stocks,papers,models,education,media,wechat",
    ),
    (
        "娱乐八卦",
        KeywordRuleType.EXCLUDE,
        0.0,
        "news,github,stocks,papers,models,education,media,wechat",
    ),
]

# Near-duplicate INCLUDE keywords to drop on upgrade (keep the preferred form).
INCLUDE_DEDUP_DROP: tuple[str, ...] = (
    "AI Agent",  # keep Agent
    "大语言模型",  # keep 大模型
    "GPT",  # keep LLM
)

_ALL_EXCLUDE_SCOPES = "news,github,stocks,papers,models,education,media,wechat"
_LEGACY_BOOST_SCOPES = "news,github,stocks,papers,models,education"


def backfill_keyword_scopes(session: Session) -> int:
    """Fill empty scopes on existing rules (idempotent)."""
    rows = list(session.scalars(select(IntelKeywordRule)).all())
    n = 0
    for rule in rows:
        if (rule.scopes or "").strip():
            continue
        if rule.rule_type == KeywordRuleType.INCLUDE:
            rule.scopes = "news"
        elif rule.rule_type == KeywordRuleType.EXCLUDE:
            rule.scopes = _ALL_EXCLUDE_SCOPES
        else:
            rule.scopes = _LEGACY_BOOST_SCOPES
        n += 1
    if n:
        session.flush()
    return n


def dedupe_include_keywords(session: Session) -> int:
    """Remove semantically duplicate INCLUDE seed keywords from existing DBs."""
    deleted = 0
    for keyword in INCLUDE_DEDUP_DROP:
        rows = list(
            session.scalars(
                select(IntelKeywordRule).where(
                    IntelKeywordRule.keyword == keyword,
                    IntelKeywordRule.rule_type == KeywordRuleType.INCLUDE,
                )
            ).all()
        )
        for rule in rows:
            session.delete(rule)
            deleted += 1
    if deleted:
        session.flush()
    return deleted


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
        "keywords_deduped": 0,
        "scopes_backfilled": 0,
        "github_queries": 0,
        "paper_sources": 0,
        "stock_sources": 0,
        "users": 0,
        "reddit_sources": 0,
        "x_sources": 0,
    }
    admin = ensure_default_admin(session)
    created["users"] = 1 if admin is not None else 0
    # Shared catalog types (news / github / papers / education) keep owner_id NULL
    # so all users can review them. Do not claim null-owner rows for the admin.

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
        for keyword, rule_type, weight, scopes in DEFAULT_KEYWORDS:
            session.add(
                IntelKeywordRule(
                    keyword=keyword,
                    rule_type=rule_type,
                    weight=weight,
                    enabled=True,
                    scopes=scopes,
                )
            )
            created["keywords"] += 1
    else:
        created["keywords_deduped"] = dedupe_include_keywords(session)
        created["scopes_backfilled"] = backfill_keyword_scopes(session)

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
    created["x_sources"] = ensure_x_sources(session)
    created["model_sources_deduped"] = dedupe_model_sources(session)
    created["model_sources"] = ensure_model_sources(session)
    created["education_sources"] = ensure_education_sources(session)
    created["education_sources_repaired"] = repair_education_sources(session)
    created["news_sources_repaired"] = repair_news_sources(session)
    created["paper_sources_repaired"] = repair_paper_sources(session)
    created["shared_catalog_owners_repaired"] = repair_shared_catalog_owners(session)

    session.flush()
    return created


# Overlapping feeds from the first model-source seed; keep one HF + one MS.
_OBSOLETE_MODEL_URLS = frozenset(
    {
        "hf:models:downloads",
        "hf:models:pipeline:text-generation",
        "ms:models:downloads",
        "ms:models:search:qwen",
    }
)

_CANONICAL_MODEL_NAMES: dict[str, str] = {
    "hf:models": "Hugging Face",
    "ms:models": "ModelScope 魔搭",
}


def _norm_source_url(url: str | None) -> str:
    return (url or "").strip().lower()


def dedupe_model_sources(session: Session) -> int:
    """Remove duplicate / obsolete MODEL sources; normalize canonical names.

    Returns the number of rows deleted.
    """
    from bagel.domain.models import IntelItem

    rows = list(
        session.scalars(
            select(IntelSource)
            .where(IntelSource.source_type == SourceType.MODEL)
            .order_by(IntelSource.priority.asc(), IntelSource.created_at.asc())
        ).all()
    )
    kept: dict[str, IntelSource] = {}
    to_delete: list[IntelSource] = []
    for src in rows:
        key = _norm_source_url(src.url)
        if key in _OBSOLETE_MODEL_URLS:
            to_delete.append(src)
            continue
        if key in kept:
            existing = kept[key]
            if not existing.enabled and src.enabled:
                to_delete.append(existing)
                kept[key] = src
            else:
                to_delete.append(src)
            continue
        kept[key] = src
        canon = _CANONICAL_MODEL_NAMES.get(key)
        if canon and src.name != canon:
            src.name = canon

    for src in to_delete:
        # Detach items so FK does not block source deletion.
        session.execute(
            update(IntelItem)
            .where(IntelItem.source_id == src.id)
            .values(source_id=None)
        )
        session.delete(src)
    if to_delete:
        session.flush()
    return len(to_delete)


def ensure_model_sources(session: Session) -> int:
    """Idempotently add default Hugging Face / ModelScope model sources."""
    existing_urls = {
        _norm_source_url(u)
        for u in session.scalars(
            select(IntelSource.url).where(IntelSource.source_type == SourceType.MODEL)
        ).all()
    }
    added = 0
    for row in DEFAULT_MODEL_SOURCES:
        url = str(row["url"]).strip()
        if _norm_source_url(url) in existing_urls:
            continue
        session.add(
            IntelSource(
                name=row["name"],
                url=url,
                source_type=SourceType.MODEL,
                region=row.get("region", Region.GLOBAL),
                network_requirement=row.get("network", NetworkRequirement.PROXY_PREFERRED),
                priority=row.get("priority", 100),
                enabled=row.get("enabled", True),
            )
        )
        existing_urls.add(_norm_source_url(url))
        added += 1
    return added


def ensure_education_sources(session: Session) -> int:
    """Idempotently add default university / OCW education sources."""
    existing_urls = {
        _norm_source_url(u)
        for u in session.scalars(
            select(IntelSource.url).where(IntelSource.source_type == SourceType.EDUCATION)
        ).all()
    }
    added = 0
    for row in DEFAULT_EDUCATION_SOURCES:
        url = str(row["url"]).strip()
        if _norm_source_url(url) in existing_urls:
            continue
        session.add(
            IntelSource(
                name=row["name"],
                url=url,
                source_type=SourceType.EDUCATION,
                region=row.get("region", Region.GLOBAL),
                network_requirement=row.get("network", NetworkRequirement.PROXY_PREFERRED),
                priority=row.get("priority", 100),
                enabled=row.get("enabled", True),
            )
        )
        existing_urls.add(_norm_source_url(url))
        added += 1
    return added


def repair_education_sources(session: Session) -> int:
    """Migrate broken education feed URLs and disable dead ones (idempotent)."""
    changed = 0
    rows = list(
        session.scalars(
            select(IntelSource).where(IntelSource.source_type == SourceType.EDUCATION)
        ).all()
    )
    occupied = {_norm_source_url(r.url) for r in rows}

    for src in rows:
        raw = (src.url or "").strip()
        if raw not in _EDUCATION_URL_MIGRATIONS:
            continue
        new_url = _EDUCATION_URL_MIGRATIONS[raw]
        if not new_url:
            if src.enabled:
                src.enabled = False
                src.last_error_code = "FEED_GONE"
                changed += 1
            continue
        norm_new = _norm_source_url(new_url)
        if norm_new == _norm_source_url(raw):
            continue
        if norm_new in occupied:
            if src.enabled:
                src.enabled = False
                src.last_error_code = "FEED_REPLACED"
                changed += 1
            continue
        occupied.discard(_norm_source_url(raw))
        occupied.add(norm_new)
        src.url = new_url
        src.last_error_code = None
        if new_url in _EDUCATION_NAME_FIXES:
            src.name = _EDUCATION_NAME_FIXES[new_url]
        src.enabled = True
        changed += 1
    return changed


def repair_news_sources(session: Session) -> int:
    """Migrate broken news feed URLs, disable dead ones, ensure extras (idempotent)."""
    changed = 0
    rows = list(
        session.scalars(
            select(IntelSource).where(
                IntelSource.source_type.in_([SourceType.RSS, SourceType.RSSHUB])
            )
        ).all()
    )
    occupied = {_norm_source_url(r.url) for r in rows}

    for src in rows:
        raw = (src.url or "").strip()
        if raw in _NEWS_DISABLE_URLS:
            if src.enabled:
                src.enabled = False
                src.last_error_code = "FEED_UNRELIABLE"
                changed += 1
            continue
        if raw not in _NEWS_URL_MIGRATIONS:
            continue
        new_url = _NEWS_URL_MIGRATIONS[raw]
        if not new_url:
            if src.enabled:
                src.enabled = False
                src.last_error_code = "FEED_GONE"
                changed += 1
            continue
        norm_new = _norm_source_url(new_url)
        if norm_new == _norm_source_url(raw):
            continue
        if norm_new in occupied:
            if src.enabled:
                src.enabled = False
                src.last_error_code = "FEED_REPLACED"
                changed += 1
            continue
        occupied.discard(_norm_source_url(raw))
        occupied.add(norm_new)
        src.url = new_url
        src.last_error_code = None
        if new_url in _NEWS_NAME_FIXES:
            src.name = _NEWS_NAME_FIXES[new_url]
        src.enabled = True
        changed += 1

    existing_urls = {_norm_source_url(u) for u in session.scalars(select(IntelSource.url)).all()}
    for row in _NEWS_ENSURE_EXTRA:
        url = str(row["url"]).strip()
        if _norm_source_url(url) in existing_urls:
            continue
        session.add(
            IntelSource(
                name=row["name"],
                url=url,
                source_type=row.get("source_type", SourceType.RSS),
                region=row.get("region", Region.CN),
                network_requirement=row.get("network", NetworkRequirement.DIRECT),
                priority=row.get("priority", 100),
                enabled=row.get("enabled", True),
            )
        )
        existing_urls.add(_norm_source_url(url))
        changed += 1
    return changed


def repair_paper_sources(session: Session) -> int:
    """Disable Semantic Scholar by default (anonymous search often 429)."""
    changed = 0
    rows = list(
        session.scalars(
            select(IntelSource).where(IntelSource.source_type == SourceType.PAPER)
        ).all()
    )
    for src in rows:
        url = (src.url or "").strip().lower()
        if not (url.startswith("s2:") or "semanticscholar.org" in url):
            continue
        if src.enabled:
            src.enabled = False
            src.last_error_code = "DEFAULT_OFF_RATE_LIMIT"
            changed += 1
    return changed


# Catalog tabs shared across users — collectors leave owner_id NULL.
_SHARED_CATALOG_TYPES: tuple[str, ...] = (
    ItemType.NEWS,
    ItemType.GITHUB_REPO,
    ItemType.GITHUB_RELEASE,
    ItemType.PAPER,
    ItemType.EDUCATION,
)


def repair_shared_catalog_owners(session: Session) -> int:
    """Undo mistaken admin claim on shared news/github/papers/education rows."""
    result = session.execute(
        update(IntelItem)
        .where(IntelItem.item_type.in_(_SHARED_CATALOG_TYPES))
        .where(IntelItem.owner_id.is_not(None))
        .values(owner_id=None)
    )
    return int(result.rowcount or 0)


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


def ensure_x_sources(session: Session) -> int:
    """Add missing X (Twitter) RSSHub sources for existing databases."""
    existing_urls = {
        (u or "").strip().lower()
        for u in session.scalars(select(IntelSource.url)).all()
    }
    added = 0
    for row in DEFAULT_X_SOURCES:
        url = str(row["url"]).strip()
        if url.lower() in existing_urls:
            continue
        session.add(
            IntelSource(
                name=row["name"],
                url=url,
                source_type=row.get("source_type", SourceType.RSSHUB),
                region=row.get("region", Region.GLOBAL),
                network_requirement=row.get("network", NetworkRequirement.PROXY_PREFERRED),
                priority=row.get("priority", 230),
                enabled=row.get("enabled", True),
            )
        )
        existing_urls.add(url.lower())
        added += 1
    if added:
        session.flush()
    return added
