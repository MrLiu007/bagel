"""Domain enums for IntelItem lifecycle and related types.

Values are stored as plain strings in the DB for SQLite/Postgres portability.
Keep enum members stable — renaming breaks existing rows and seed data.
"""

from __future__ import annotations

from enum import StrEnum


class ItemType(StrEnum):
    """High-level content kinds shown as separate product tabs."""

    NEWS = "NEWS"
    GITHUB_REPO = "GITHUB_REPO"
    GITHUB_RELEASE = "GITHUB_RELEASE"
    MEDIA_POST = "MEDIA_POST"
    WECHAT_MSG = "WECHAT_MSG"
    PAPER = "PAPER"
    STOCK_NEWS = "STOCK_NEWS"
    MODEL = "MODEL"
    EDUCATION = "EDUCATION"
    # Reserved for future collectors (not wired in MVP UI):
    BLOG = "BLOG"
    DATASET = "DATASET"
    ANNOUNCEMENT = "ANNOUNCEMENT"


class ItemStatus(StrEnum):
    """Pipeline / review lifecycle for a single IntelItem."""

    DISCOVERED = "DISCOVERED"
    NORMALIZED = "NORMALIZED"
    CANDIDATE = "CANDIDATE"
    REJECTED = "REJECTED"
    SELECTED = "SELECTED"
    SUMMARIZED = "SUMMARIZED"
    PUBLISHED = "PUBLISHED"
    WIKI_EXPORTED = "WIKI_EXPORTED"


class SourceType(StrEnum):
    """How an IntelSource (or ad-hoc fetch) obtains data."""

    RSS = "RSS"
    RSSHUB = "RSSHUB"
    GITHUB = "GITHUB"
    MANUAL = "MANUAL"
    MEDIA = "MEDIA"
    WECHAT = "WECHAT"
    PAPER = "PAPER"
    STOCK = "STOCK"
    MODEL = "MODEL"
    EDUCATION = "EDUCATION"


class Region(StrEnum):
    """Rough geography hint for network routing / degrade decisions."""

    CN = "CN"
    GLOBAL = "GLOBAL"


class NetworkRequirement(StrEnum):
    """Whether a source prefers a proxy (overseas) or direct access."""

    DIRECT = "DIRECT"
    PROXY_PREFERRED = "PROXY_PREFERRED"


class KeywordRuleType(StrEnum):
    """INCLUDE requires a match when any INCLUDE rules exist; EXCLUDE rejects."""

    INCLUDE = "INCLUDE"
    EXCLUDE = "EXCLUDE"
    BOOST = "BOOST"


class KeywordScope(StrEnum):
    """Resource categories a keyword rule may apply to (stored in scopes CSV)."""

    NEWS = "news"
    GITHUB = "github"
    STOCKS = "stocks"
    PAPERS = "papers"
    MODELS = "models"
    EDUCATION = "education"
    MEDIA = "media"
    WECHAT = "wechat"


class BriefKind(StrEnum):
    """Weekly / monthly brief templates (SCIENCE == papers UI)."""

    NEWS = "NEWS"
    GITHUB = "GITHUB"
    SCIENCE = "SCIENCE"
    MEDIA = "MEDIA"
    STOCK = "STOCK"
    MODEL = "MODEL"
    EDUCATION = "EDUCATION"


class JobStatus(StrEnum):
    """Outcome of a collect / digest / brief job run."""

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ErrorCode(StrEnum):
    """Stable machine-readable codes for job / health reporting."""

    NETWORK_UNREACHABLE = "NETWORK_UNREACHABLE"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    HTTP_ERROR = "HTTP_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILED = "AUTH_FAILED"
    PARSE_ERROR = "PARSE_ERROR"
    INVALID_DATA = "INVALID_DATA"
    LLM_ERROR = "LLM_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class GithubChangeType(StrEnum):
    """Why a GitHub repo/item was surfaced to the review queue."""

    NEW_REPO = "NEW_REPO"
    NEW_RELEASE = "NEW_RELEASE"
    RECENT_ACTIVITY = "RECENT_ACTIVITY"
    STAR_GROWTH = "STAR_GROWTH"
