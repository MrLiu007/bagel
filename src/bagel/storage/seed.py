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
    {
        "name": "少数派",
        "url": "https://sspai.com/feed",
        "region": Region.CN,
        "priority": 40,
        "enabled": False,  # lifestyle / gadget — not AI/tech industry focus
    },
    {"name": "Solidot", "url": "https://www.solidot.org/index.rss", "region": Region.CN, "priority": 50},
    {
        "name": "36氪",
        "url": "https://36kr.com/feed",
        "region": Region.CN,
        "priority": 60,
        "enabled": False,  # feed often empty / non-RSS shell
    },
    {
        "name": "IT之家",
        "url": "https://www.ithome.com/rss/",
        "region": Region.CN,
        "priority": 70,
        "enabled": False,  # consumer gadget noise vs AI/robotics
    },
    {"name": "OSCHINA", "url": "https://www.oschina.net/news/rss", "region": Region.CN, "priority": 80},
    {
        "name": "掘金后端",
        "url": "https://juejin.cn/rss",
        "region": Region.CN,
        "priority": 90,
        "enabled": False,  # tutorial noise
    },
    {
        "name": "博客园精华",
        "url": "https://feed.cnblogs.com/blog/sitehome/rss",
        "region": Region.CN,
        "priority": 100,
        "enabled": False,  # general blogging, weak AI signal
    },
    {"name": "爱范儿", "url": "https://www.ifanr.com/feed", "region": Region.CN, "priority": 105},
    # --- GLOBAL (labs + AI-focused outlets; prefer proxy) ---
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
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 95},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 100},
    {"name": "Wired AI", "url": "https://www.wired.com/feed/tag/ai/latest/rss", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 105},
    {"name": "IEEE Spectrum AI", "url": "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss", "region": Region.GLOBAL, "network": NetworkRequirement.PROXY_PREFERRED, "priority": 108},
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
    # --- Reddit (official .rss; easy 429 — keep one by default) ---
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
        "enabled": False,  # 429 when many Reddit feeds fire in one job
    },
    {
        "name": "Reddit r/artificial",
        "url": "https://www.reddit.com/r/artificial/new/.rss",
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 180,
        "enabled": False,
    },
    {
        "name": "Reddit r/LanguageTechnology",
        "url": "https://www.reddit.com/r/LanguageTechnology/new/.rss",
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 190,
        "enabled": False,
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
    # Hugging Face Daily Papers is curated arXiv — same abs URL / paper_identity_hash
    # as arXiv feeds, so the「Hugging Face」filter tab never owns a distinct catalog.
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
    # Global courses / AI education news only (no campus PR, no fragile RSSHub).
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
        "name": "Stanford AI Lab Blog",
        "url": "https://ai.stanford.edu/blog/feed.xml",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 20,
    },
    {
        "name": "Yale Open Courses",
        "url": "https://oyc.yale.edu/rss.xml",
        "source_type": SourceType.EDUCATION,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 30,
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
    "https://www.harvardonline.harvard.edu/blog/rss.xml": "",  # was mapped to Gazette; both pruned
}

_EDUCATION_NAME_FIXES: dict[str, str] = {
    "https://old.ocw.mit.edu/rss/new/mit-newcourses.xml": "MIT OCW · New Courses",
    "https://ai.stanford.edu/blog/feed.xml": "Stanford AI Lab Blog",
}

# Delete from existing DBs: campus PR, 403 feeds, fragile CN RSSHub adapters.
_EDUCATION_DELETE_URLS: frozenset[str] = frozenset(
    {
        "https://www.classcentral.com/report/feed/",
        "https://news.berkeley.edu/feed/",
        "https://news.harvard.edu/gazette/feed/",
        "https://news.mit.edu/rss/feed",
        "/xuetangx/courses",
        "/universities/pku/opencourse",
    }
)

_STOCK_DELETE_URLS: frozenset[str] = frozenset(
    {
        "/cls/telegraph",
        "/eastmoney/report/strategyreport",
        "/wallstreetcn/hot",
    }
)

# Seed INCLUDE keywords that should also gate GitHub after consolidating queries.
_GITHUB_INCLUDE_SEED_KEYWORDS: frozenset[str] = frozenset(
    {
        "GPT",
        "ChatGPT",
        "OpenAI",
        "Claude",
        "Anthropic",
        "Gemini",
        "Agent",
        "RAG",
        "LLM",
        "大模型",
        "multimodal",
        "reasoning",
        "robotics",
        "robot",
        "机器人",
        "embodied AI",
        "AGI",
    }
)

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
        "https://sspai.com/feed",
        "https://36kr.com/feed",
        "https://www.ithome.com/rss/",
        "https://juejin.cn/rss",
        "https://feed.cnblogs.com/blog/sitehome/rss",
        "https://www.cnblogs.com/aggsite/rss",
        # Anthropic seed is not a real RSS body (PARSE_ERROR).
        "https://raw.githubusercontent.com/anthropics/anthropic-cookbook/main/README.md",
        # Extra Reddit feeds — keep only r/MachineLearning enabled by default.
        "https://www.reddit.com/r/LocalLLaMA/new/.rss",
        "https://www.reddit.com/r/artificial/new/.rss",
        "https://www.reddit.com/r/LanguageTechnology/new/.rss",
        # RSSHub adapters: need healthy RSSHUB_BASE_URL; commonly 502.
        "/weibo/search/hot",
        "/github/trending/daily/python",
        "/reddit/user/username/submitted",
        "/twitter/user/OpenAI",
        "/twitter/user/AnthropicAI",
        "/twitter/user/HuggingFace",
        "/twitter/user/karpathy",
        "/twitter/user/AndrewYNg",
        "/twitter/user/DeepLearningAI",
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
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 95,
    },
    {
        "name": "Wired AI",
        "url": "https://www.wired.com/feed/tag/ai/latest/rss",
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 105,
    },
    {
        "name": "IEEE Spectrum AI",
        "url": "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss",
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 108,
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
]

# Learning AV — yt-dlp channel / playlist / page URLs (see docs/default-av-sources.md)
# Smoke sources first (no browser Cookie) so download pipeline can be verified without Bilibili.
DEFAULT_AV_SOURCES: list[dict] = [
    {
        "name": "验通·直链样片（免 Cookie）",
        "url": (
            "av:generic:url:https://upload.wikimedia.org/wikipedia/commons/"
            "transcoded/c/c0/Big_Buck_Bunny_4K.webm/"
            "Big_Buck_Bunny_4K.webm.360p.vp9.webm"
        ),
        "source_type": SourceType.AV,
        "region": Region.CN,
        "network": NetworkRequirement.DIRECT,
        "priority": 1,
    },
    {
        "name": "验通·Internet Archive",
        "url": "av:generic:url:https://archive.org/details/BigBuckBunny_328",
        "source_type": SourceType.AV,
        "region": Region.GLOBAL,
        "network": NetworkRequirement.PROXY_PREFERRED,
        "priority": 2,
    },
    {
        "name": "跟李沐学 AI",
        "url": "av:bilibili:mid:1567748478",
        "source_type": SourceType.AV,
        "region": Region.CN,
        "network": NetworkRequirement.DIRECT,
        "priority": 10,
    },
    {
        "name": "机器之心官方",
        "url": "av:bilibili:mid:73414544",
        "source_type": SourceType.AV,
        "region": Region.CN,
        "network": NetworkRequirement.DIRECT,
        "priority": 15,
    },
    {
        "name": "爱可可-爱生活",
        "url": "av:bilibili:mid:23852932",
        "source_type": SourceType.AV,
        "region": Region.CN,
        "network": NetworkRequirement.DIRECT,
        "priority": 20,
    },
    {
        "name": "量子位Daily",
        "url": "av:bilibili:mid:3546619041548912",
        "source_type": SourceType.AV,
        "region": Region.CN,
        "network": NetworkRequirement.DIRECT,
        "priority": 25,
    },
]

# Canonical AV source URLs retained by repair_av_sources (purge everything else).
_AV_KEEP_URLS = frozenset(str(r["url"]).strip() for r in DEFAULT_AV_SOURCES)

DEFAULT_KEYWORDS: list[tuple[str, str, float, str]] = [
    # INCLUDE — tech / AI / LLM / robotics gate for news (+ github).
    # GPT is NOT ≈ LLM: titles like "GPT-6" never contain "llm".
    ("GPT", KeywordRuleType.INCLUDE, 2.5, "news,github"),
    ("ChatGPT", KeywordRuleType.INCLUDE, 2.0, "news,github"),
    ("OpenAI", KeywordRuleType.INCLUDE, 2.0, "news,github"),
    ("Claude", KeywordRuleType.INCLUDE, 2.0, "news,github"),
    ("Anthropic", KeywordRuleType.INCLUDE, 1.8, "news,github"),
    ("Gemini", KeywordRuleType.INCLUDE, 2.0, "news,github"),
    ("LLM", KeywordRuleType.INCLUDE, 2.0, "news,github"),
    ("大模型", KeywordRuleType.INCLUDE, 2.0, "news,github"),
    ("人工智能", KeywordRuleType.INCLUDE, 2.0, "news"),
    ("生成式", KeywordRuleType.INCLUDE, 1.8, "news"),
    ("Agent", KeywordRuleType.INCLUDE, 2.0, "news,github"),
    ("RAG", KeywordRuleType.INCLUDE, 2.0, "news,github"),
    ("multimodal", KeywordRuleType.INCLUDE, 1.5, "news,github"),
    ("reasoning", KeywordRuleType.INCLUDE, 1.5, "news,github"),
    ("robotics", KeywordRuleType.INCLUDE, 2.0, "news,github"),
    ("robot", KeywordRuleType.INCLUDE, 1.8, "news,github"),
    ("机器人", KeywordRuleType.INCLUDE, 2.0, "news,github"),
    ("embodied AI", KeywordRuleType.INCLUDE, 2.0, "news,github"),
    ("具身", KeywordRuleType.INCLUDE, 1.8, "news"),
    ("AGI", KeywordRuleType.INCLUDE, 1.5, "news,github"),
    # BOOST — score only (do not gate). "开源" alone is too broad as INCLUDE.
    ("开源", KeywordRuleType.BOOST, 1.2, "news,github"),
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
        "news,github,stocks,papers,models,education,media,wechat,av",
    ),
    (
        "荐股",
        KeywordRuleType.EXCLUDE,
        0.0,
        "news,github,stocks,papers,models,education,media,wechat,av",
    ),
    (
        "付费课程",
        KeywordRuleType.EXCLUDE,
        0.0,
        "news,github,stocks,papers,models,education,media,wechat,av",
    ),
    (
        "娱乐八卦",
        KeywordRuleType.EXCLUDE,
        0.0,
        "news,github,stocks,papers,models,education,media,wechat,av",
    ),
]

# Near-duplicate INCLUDE keywords to drop on upgrade (keep the preferred form).
INCLUDE_DEDUP_DROP: tuple[str, ...] = (
    "AI Agent",  # keep Agent
    "大语言模型",  # keep 大模型
)

_ALL_EXCLUDE_SCOPES = "news,github,stocks,papers,models,education,media,wechat,av"
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


def _merge_scope_csv(existing: str | None, wanted: str) -> str:
    scopes: list[str] = []
    for part in f"{existing or ''},{wanted}".split(","):
        s = part.strip()
        if s and s not in scopes:
            scopes.append(s)
    return ",".join(scopes)


def ensure_default_interest_keywords(session: Session) -> int:
    """Upsert seed INCLUDE/BOOST/EXCLUDE so GPT-6-style titles are not filtered out.

    - Adds missing seed keywords
    - Merges scopes on existing same keyword+type
    - Converts legacy INCLUDE「开源」→ BOOST (too broad as a gate)
    """
    changed = 0
    rows = list(session.scalars(select(IntelKeywordRule)).all())
    by_key: dict[tuple[str, str], IntelKeywordRule] = {
        (r.keyword, r.rule_type): r for r in rows
    }

    # Legacy: 「开源」as INCLUDE rejects unrelated AI news that omit the word,
    # and accepts general OSS posts — demote to BOOST.
    legacy = by_key.get(("开源", KeywordRuleType.INCLUDE))
    if legacy is not None:
        boost = by_key.get(("开源", KeywordRuleType.BOOST))
        if boost is None:
            legacy.rule_type = KeywordRuleType.BOOST
            legacy.weight = 1.2
            legacy.scopes = _merge_scope_csv(legacy.scopes, "news,github")
            by_key[("开源", KeywordRuleType.BOOST)] = legacy
            by_key.pop(("开源", KeywordRuleType.INCLUDE), None)
            changed += 1
        else:
            boost.scopes = _merge_scope_csv(boost.scopes, legacy.scopes or "news,github")
            session.delete(legacy)
            by_key.pop(("开源", KeywordRuleType.INCLUDE), None)
            changed += 1

    for keyword, rule_type, weight, scopes in DEFAULT_KEYWORDS:
        key = (keyword, rule_type)
        existing = by_key.get(key)
        if existing is None:
            session.add(
                IntelKeywordRule(
                    keyword=keyword,
                    rule_type=rule_type,
                    weight=weight,
                    enabled=True,
                    scopes=scopes,
                )
            )
            changed += 1
            continue
        merged = _merge_scope_csv(existing.scopes, scopes)
        if merged != (existing.scopes or "").strip():
            existing.scopes = merged
            changed += 1
        if existing.enabled is False and rule_type == KeywordRuleType.INCLUDE:
            # Re-enable seed INCLUDE tags if user disabled GPT/LLM gate by accident.
            # Leave EXCLUDE alone.
            pass
    if changed:
        session.flush()
    return changed


# Single github.com Search entry. Topic keep/reject is owned by INCLUDE tags
# (KeywordScope.GITHUB) — multiple topic queries duplicated that role and burned API quota.
DEFAULT_GITHUB_QUERIES: list[tuple[str, str]] = [
    (
        "GitHub",
        (
            "(llm OR agent OR rag OR multimodal OR \"large language model\" OR "
            "\"machine learning\" OR \"deep learning\") "
            "in:name,description,topics stars:>30"
        ),
    ),
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
    created["keywords_ensured"] = ensure_default_interest_keywords(session)

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
    created["av_sources"] = ensure_av_sources(session)
    created["av_sources_repaired"] = repair_av_sources(session)
    created["news_sources_repaired"] = repair_news_sources(session)
    created["paper_sources_repaired"] = repair_paper_sources(session)
    created["stock_sources_repaired"] = repair_stock_sources(session)
    created["github_queries_repaired"] = repair_github_queries(session)
    created["github_include_scopes_repaired"] = repair_github_include_scopes(session)
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


def ensure_av_sources(session: Session) -> int:
    """Idempotently add default learning AV sources."""
    existing_urls = {
        _norm_source_url(u)
        for u in session.scalars(
            select(IntelSource.url).where(IntelSource.source_type == SourceType.AV)
        ).all()
    }
    added = 0
    for row in DEFAULT_AV_SOURCES:
        url = str(row["url"]).strip()
        if _norm_source_url(url) in existing_urls:
            continue
        session.add(
            IntelSource(
                name=row["name"],
                url=url,
                source_type=SourceType.AV,
                region=row.get("region", Region.GLOBAL),
                network_requirement=row.get("network", NetworkRequirement.PROXY_PREFERRED),
                priority=row.get("priority", 100),
                enabled=row.get("enabled", True),
            )
        )
        existing_urls.add(_norm_source_url(url))
        added += 1
    return added


# Wrong mid → correct mid (verified space.bilibili.com/{mid}).
_AV_URL_MIGRATIONS: dict[str, str] = {
    "av:bilibili:mid:15634833": "av:bilibili:mid:1567748478",
    "av:bilibili:mid:320334464": "av:bilibili:mid:73414544",
}

# Legacy / campus PR rows we still purge; user-added http(s) / custom av: are kept.
_AV_LEGACY_PURGE_URLS = frozenset(
    {
        "av:bilibili:mid:515087961",  # 清华大学（非学习主路径）
        *_AV_URL_MIGRATIONS.keys(),
    }
)

_AV_NAME_FIXES: dict[str, str] = {
    "av:generic:url:https://upload.wikimedia.org/wikipedia/commons/transcoded/c/c0/Big_Buck_Bunny_4K.webm/Big_Buck_Bunny_4K.webm.360p.vp9.webm": "验通·直链样片（免 Cookie）",
    "av:generic:url:https://archive.org/details/BigBuckBunny_328": "验通·Internet Archive",
    "av:bilibili:mid:1567748478": "跟李沐学 AI",
    "av:bilibili:mid:73414544": "机器之心官方",
    "av:bilibili:mid:23852932": "爱可可-爱生活",
    "av:bilibili:mid:3546619041548912": "量子位Daily",
}


def _is_user_av_source_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if lower.startswith(("http://", "https://")):
        return True
    if lower.startswith("av:") and raw not in _AV_LEGACY_PURGE_URLS:
        return True
    return False


def repair_av_sources(session: Session) -> int:
    """Migrate/rename canonical AV defaults; purge known legacy only; keep user sources."""
    changed = 0
    rows = list(
        session.scalars(select(IntelSource).where(IntelSource.source_type == SourceType.AV)).all()
    )
    occupied = {_norm_source_url(r.url) for r in rows}

    for src in rows:
        raw = (src.url or "").strip()
        new_url = _AV_URL_MIGRATIONS.get(raw)
        if new_url:
            norm_new = _norm_source_url(new_url)
            if norm_new in occupied and norm_new != _norm_source_url(raw):
                session.delete(src)
                changed += 1
                continue
            occupied.discard(_norm_source_url(raw))
            occupied.add(norm_new)
            src.url = new_url
            src.last_error_code = None
            changed += 1
            raw = new_url

        if raw in _AV_LEGACY_PURGE_URLS or (
            raw not in _AV_KEEP_URLS and not _is_user_av_source_url(raw)
        ):
            session.delete(src)
            occupied.discard(_norm_source_url(raw))
            changed += 1
            continue

        fix_name = _AV_NAME_FIXES.get(raw)
        if fix_name and src.name != fix_name:
            src.name = fix_name
            changed += 1
        if raw in _AV_KEEP_URLS and (not src.enabled or src.last_error_code):
            src.enabled = True
            src.last_error_code = None
            changed += 1

    # Dedupe by URL — keep one enabled row.
    rows = list(
        session.scalars(select(IntelSource).where(IntelSource.source_type == SourceType.AV)).all()
    )
    by_url: dict[str, list[IntelSource]] = {}
    for src in rows:
        by_url.setdefault(_norm_source_url(src.url), []).append(src)
    for group in by_url.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda s: (0 if s.enabled else 1, s.priority, str(s.id)))
        for dup in group[1:]:
            session.delete(dup)
            changed += 1

    return changed

def repair_education_sources(session: Session) -> int:
    """Migrate broken education feeds; delete campus PR / 403 / CN RSSHub rows."""
    from bagel.domain.models import IntelItem

    changed = 0
    rows = list(
        session.scalars(
            select(IntelSource).where(IntelSource.source_type == SourceType.EDUCATION)
        ).all()
    )
    occupied = {_norm_source_url(r.url) for r in rows}
    to_delete: list[IntelSource] = []

    for src in rows:
        raw = (src.url or "").strip()
        if raw in _EDUCATION_DELETE_URLS or _norm_source_url(raw) in {
            _norm_source_url(u) for u in _EDUCATION_DELETE_URLS
        }:
            to_delete.append(src)
            continue
        if raw not in _EDUCATION_URL_MIGRATIONS:
            continue
        new_url = _EDUCATION_URL_MIGRATIONS[raw]
        if not new_url:
            to_delete.append(src)
            continue
        norm_new = _norm_source_url(new_url)
        if norm_new == _norm_source_url(raw):
            continue
        if norm_new in occupied:
            to_delete.append(src)
            continue
        occupied.discard(_norm_source_url(raw))
        occupied.add(norm_new)
        src.url = new_url
        src.last_error_code = None
        if new_url in _EDUCATION_NAME_FIXES:
            src.name = _EDUCATION_NAME_FIXES[new_url]
        src.enabled = True
        changed += 1

    for src in to_delete:
        session.execute(
            update(IntelItem).where(IntelItem.source_id == src.id).values(source_id=None)
        )
        session.delete(src)
        changed += 1
    if changed:
        session.flush()
    return changed


def repair_stock_sources(session: Session) -> int:
    """Remove fragile CN RSSHub stock adapters (HTTP_ERROR in practice)."""
    from bagel.domain.models import IntelItem

    rows = list(
        session.scalars(
            select(IntelSource).where(IntelSource.source_type == SourceType.STOCK)
        ).all()
    )
    delete_norms = {_norm_source_url(u) for u in _STOCK_DELETE_URLS}
    to_delete = [s for s in rows if _norm_source_url(s.url) in delete_norms]
    for src in to_delete:
        session.execute(
            update(IntelItem).where(IntelItem.source_id == src.id).values(source_id=None)
        )
        session.delete(src)
    if to_delete:
        session.flush()
    return len(to_delete)


def repair_github_queries(session: Session) -> int:
    """Keep a single github.com Search query; topic filtering uses INCLUDE tags."""
    from bagel.domain.models import IntelGithubQuery

    canon_name, canon_query = DEFAULT_GITHUB_QUERIES[0]
    rows = list(
        session.scalars(select(IntelGithubQuery).order_by(IntelGithubQuery.created_at)).all()
    )
    changed = 0
    kept: IntelGithubQuery | None = next((r for r in rows if r.name == canon_name), None)
    if kept is None and rows:
        kept = rows[0]
    for row in rows:
        if row is kept:
            continue
        session.delete(row)
        changed += 1
    if kept is None:
        session.add(IntelGithubQuery(name=canon_name, query=canon_query, enabled=True))
        changed += 1
    else:
        if kept.name != canon_name:
            kept.name = canon_name
            changed += 1
        if (kept.query or "").strip() != canon_query:
            kept.query = canon_query
            changed += 1
        if not kept.enabled:
            kept.enabled = True
            changed += 1
    if changed:
        session.flush()
    return changed


def repair_github_include_scopes(session: Session) -> int:
    """Ensure seed topic INCLUDE tags also apply to GitHub scope."""
    changed = 0
    rows = list(
        session.scalars(
            select(IntelKeywordRule).where(
                IntelKeywordRule.rule_type == KeywordRuleType.INCLUDE,
                IntelKeywordRule.keyword.in_(sorted(_GITHUB_INCLUDE_SEED_KEYWORDS)),
            )
        ).all()
    )
    for rule in rows:
        scopes = [s.strip() for s in (rule.scopes or "").split(",") if s.strip()]
        if "github" in scopes:
            continue
        scopes.append("github")
        # Keep news first when present for stable UI ordering.
        ordered: list[str] = []
        for key in ("news", "github"):
            if key in scopes and key not in ordered:
                ordered.append(key)
        for s in scopes:
            if s not in ordered:
                ordered.append(s)
        rule.scopes = ",".join(ordered)
        changed += 1
    if changed:
        session.flush()
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
    disable_norms = {_norm_source_url(u) for u in _NEWS_DISABLE_URLS}

    for src in rows:
        raw = (src.url or "").strip()
        norm = _norm_source_url(raw)
        if raw in _NEWS_URL_MIGRATIONS:
            new_url = _NEWS_URL_MIGRATIONS[raw]
            if not new_url:
                if src.enabled:
                    src.enabled = False
                    src.last_error_code = "FEED_GONE"
                    changed += 1
                continue
            norm_new = _norm_source_url(new_url)
            if norm_new != norm:
                if norm_new in occupied and norm_new != norm:
                    if src.enabled:
                        src.enabled = False
                        src.last_error_code = "FEED_REPLACED"
                        changed += 1
                    continue
                occupied.discard(norm)
                occupied.add(norm_new)
                src.url = new_url
                src.last_error_code = None
                if new_url in _NEWS_NAME_FIXES:
                    src.name = _NEWS_NAME_FIXES[new_url]
                changed += 1
                raw = new_url
                norm = norm_new
        if raw in _NEWS_DISABLE_URLS or norm in disable_norms:
            if src.enabled:
                src.enabled = False
                src.last_error_code = "FEED_UNRELIABLE"
                changed += 1
            continue

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


def _is_hf_paper_source(*, name: str, url: str) -> bool:
    """True for Hugging Face Daily Papers seed rows (not model hubs)."""
    blob = f"{name} {url}".lower()
    if "hf:models" in blob or "huggingface.co/api/models" in blob:
        return False
    return (
        url.strip().lower().startswith("hf:")
        or "hf:daily" in blob
        or "hf papers" in blob
        or "huggingface papers" in blob
        or ("huggingface" in blob and "paper" in blob)
    )


def repair_paper_sources(session: Session) -> int:
    """Disable S2 by default; remove obsolete Hugging Face Papers (arXiv dupes)."""
    from bagel.domain.models import IntelItem

    changed = 0
    rows = list(
        session.scalars(
            select(IntelSource).where(IntelSource.source_type == SourceType.PAPER)
        ).all()
    )
    for src in rows:
        url = (src.url or "").strip().lower()
        name = src.name or ""
        if _is_hf_paper_source(name=name, url=url):
            # Detach then delete — HF Daily Papers merge into arXiv identity hashes.
            session.execute(
                update(IntelItem)
                .where(IntelItem.source_id == src.id)
                .values(source_id=None)
            )
            session.delete(src)
            changed += 1
            continue
        if not (url.startswith("s2:") or "semanticscholar.org" in url):
            continue
        if src.enabled:
            src.enabled = False
            src.last_error_code = "DEFAULT_OFF_RATE_LIMIT"
            changed += 1
    if changed:
        session.flush()
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
