"""Domain enums for IntelItem lifecycle and related types."""

from __future__ import annotations

from enum import StrEnum


class ItemType(StrEnum):
    NEWS = "NEWS"
    GITHUB_REPO = "GITHUB_REPO"
    GITHUB_RELEASE = "GITHUB_RELEASE"
    MEDIA_POST = "MEDIA_POST"
    WECHAT_MSG = "WECHAT_MSG"
    PAPER = "PAPER"
    STOCK_NEWS = "STOCK_NEWS"
    # Future:
    BLOG = "BLOG"
    MODEL = "MODEL"
    DATASET = "DATASET"
    ANNOUNCEMENT = "ANNOUNCEMENT"


class ItemStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    NORMALIZED = "NORMALIZED"
    CANDIDATE = "CANDIDATE"
    REJECTED = "REJECTED"
    SELECTED = "SELECTED"
    SUMMARIZED = "SUMMARIZED"
    PUBLISHED = "PUBLISHED"
    WIKI_EXPORTED = "WIKI_EXPORTED"


class SourceType(StrEnum):
    RSS = "RSS"
    RSSHUB = "RSSHUB"
    GITHUB = "GITHUB"
    MANUAL = "MANUAL"
    MEDIA = "MEDIA"
    WECHAT = "WECHAT"
    PAPER = "PAPER"
    STOCK = "STOCK"


class Region(StrEnum):
    CN = "CN"
    GLOBAL = "GLOBAL"


class NetworkRequirement(StrEnum):
    DIRECT = "DIRECT"
    PROXY_PREFERRED = "PROXY_PREFERRED"


class KeywordRuleType(StrEnum):
    INCLUDE = "INCLUDE"
    EXCLUDE = "EXCLUDE"
    BOOST = "BOOST"


class BriefKind(StrEnum):
    NEWS = "NEWS"
    GITHUB = "GITHUB"
    SCIENCE = "SCIENCE"
    MEDIA = "MEDIA"
    STOCK = "STOCK"


class JobStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ErrorCode(StrEnum):
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
    NEW_REPO = "NEW_REPO"
    NEW_RELEASE = "NEW_RELEASE"
    RECENT_ACTIVITY = "RECENT_ACTIVITY"
    STAR_GROWTH = "STAR_GROWTH"
