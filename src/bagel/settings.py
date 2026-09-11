"""Application settings loaded from environment / `.env` only.

UI overrides for scheduler / Feishu live in `data/runtime_config.json`
(see `services.runtime_config`) and intentionally do not replace these env
defaults for secrets and infrastructure URLs.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class NetworkMode(StrEnum):
    AUTO = "AUTO"
    DIRECT = "DIRECT"
    PROXY = "PROXY"


class StorageBackend(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


DEFAULT_SQLITE_URL = "sqlite+pysqlite:///./data/bagel.db"


class Settings(BaseSettings):
    """Bagel runtime configuration (see `.env.example` for the full key list)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_env: str = "production"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # Storage: sqlite (default, open-source friendly) | postgres
    storage_backend: StorageBackend = StorageBackend.SQLITE
    database_url: str = DEFAULT_SQLITE_URL

    # Optional Markdown wiki export (not a replacement for the transactional DB)
    wiki_enabled: bool = False
    wiki_dir: str = "data/wiki"

    # GitHub
    github_token: str = ""
    # Semantic Scholar (optional; raises rate limits when set)
    semantic_scholar_api_key: str = ""

    # LLM (OpenAI-compatible: openai / azure / deepseek / moonshot / volcengine / custom)
    llm_enabled: bool = True
    llm_provider: str = "openai"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = 180

    # Auth
    session_secret: str = "bagel-change-me-in-production"
    auth_required: bool = True

    # Internal services
    rsshub_base_url: str = "http://localhost:1200"
    freshrss_base_url: str = "http://localhost:8080"

    # Network
    network_mode: NetworkMode = NetworkMode.AUTO
    http_proxy: str = ""
    https_proxy: str = ""
    all_proxy: str = ""
    no_proxy: str = "localhost,127.0.0.1,postgres,rsshub,freshrss"

    # Schedule
    news_collect_interval_minutes: int = 30
    github_collect_interval_minutes: int = 60
    digest_hour: int = 18

    # Features
    enable_github: bool = True
    enable_overseas_sources: bool = True
    enable_llm_summary: bool = True

    # Scheduler (env defaults; UI overrides persist in data/runtime_config.json)
    enable_scheduler: bool = False
    scheduler_jitter_seconds: int = 120

    # Feishu / Lark CLI (env defaults; UI overrides in runtime_config.json)
    enable_feishu_cli: bool = False
    feishu_cli_bin: str = "lark-cli"
    feishu_webhook_url: str = ""
    # Enterprise app for inbound bot commands (event subscription)
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""

    # Stock Phase 2
    enable_stock_enrichment: bool = True
    enable_stock_market_data: bool = True
    enable_stock_research_draft: bool = True
    stock_market_lookback_days: int = 14

    # Collect recency: only keep items published within this window
    collect_lookback_days: int = 14
    # News job pacing (sequential sources; sleep reduces Reddit/GLOBAL 429s)
    news_source_sleep_sec: float = 1.5
    news_reddit_sleep_sec: float = 8.0
    news_rate_limit_cooldown_sec: float = 18.0
    news_source_max_attempts: int = 2

    # MediaCrawler — enabled by default for out-of-box 自媒体 tab
    enable_media_crawler: bool = True
    media_crawler_enabled: bool = True
    media_crawler_path: str = "./third_party/MediaCrawler"
    # Auto git-clone on startup when checkout missing (source stays gitignored)
    media_crawler_auto_setup: bool = True
    media_crawler_git_url: str = ""  # empty → GitHub upstream; set mirror if needed
    media_crawler_git_ref: str = "main"
    media_crawler_cmd: str = "uv run main.py"
    media_crawler_platforms: str = "xhs"
    media_crawler_keywords: str = "AI,教育"
    media_crawler_login_type: str = "qrcode"
    media_crawler_max_notes: int = 8
    # Seconds between XHS page/note requests (account safety)
    media_crawler_sleep_sec: int = 6
    # Cap keywords per crawl to avoid multi-keyword burst
    media_crawler_max_keywords: int = 2
    # False = let MediaCrawler launch Chrome (QR visible). True = connect existing :9222.
    media_crawler_cdp_connect_existing: bool = False
    # False = Playwright standard browser (recommended for QR). True = CDP/Chrome debug.
    media_crawler_enable_cdp_mode: bool = False
    # Optional MediaCrawler rich output (default off — discovery stays lightweight).
    media_crawler_get_comments: bool = False
    media_crawler_get_sub_comments: bool = False
    media_crawler_get_medias: bool = False  # upstream typo ENABLE_GET_MEIDAS

    # yt-dlp — learning AV (third_party clone, not vendored)
    enable_ytdlp: bool = True
    ytdlp_enabled: bool = True
    ytdlp_path: str = "./third_party/yt-dlp"
    ytdlp_auto_setup: bool = True
    ytdlp_git_url: str = ""
    ytdlp_git_ref: str = "2026.08.19"
    av_max_items_per_source: int = 30
    av_download_dir: str = "data/av/files"
    av_default_audio_only: bool = False  # 音视频学习默认保留视频；仅音频可在 .env 打开

    av_max_height: int = 720
    av_max_file_size_mb: int = 2048
    av_write_subtitles: bool = True
    av_subtitle_langs: str = "zh,en"
    av_cookies_file: str = ""
    av_cookies_from_browser: str = ""
    av_bilibili_browser: str = "edge"  # B 站空间列表需登录态；空=不自动注入
    av_scan_sleep_sec: int = 2
    av_scan_timeout_sec: int = 120
    ffmpeg_path: str = ""
    # Local transcript when platform has no soft CC (Douyin burned-in captions, etc.)
    av_asr_enabled: bool = True
    av_asr_backend: str = "auto"  # auto | volcengine | openai | faster_whisper | off
    av_asr_model: str = "whisper-1"  # openai model, or small/base/medium for faster-whisper
    av_asr_language: str = "zh"
    # Author description is NOT on-screen captions; off by default for transcript jobs
    av_fallback_author_desc: bool = False
    # Volcengine openspeech / 豆包语音 录音文件识别（submit/query + flash）
    volc_asr_api_key: str = ""  # 新版控制台 X-Api-Key
    volc_asr_app_id: str = ""  # 旧版 APP ID → X-Api-App-Key
    volc_asr_access_key: str = ""  # 旧版 Access Token → X-Api-Access-Key
    volc_asr_resource_id: str = "volc.seedasr.auc"  # 2.0; 1.0=volc.bigasr.auc
    volc_asr_flash_resource_id: str = "volc.bigasr.auc_turbo"
    volc_asr_mode: str = "auto"  # auto | async | flash
    volc_asr_language: str = ""  # empty → reuse AV_ASR_LANGUAGE
    volc_asr_uid: str = "bagel"
    volc_asr_poll_interval_sec: float = 2.0
    volc_asr_poll_timeout_sec: float = 900.0  # long Douyin clips
    volc_asr_http_timeout_sec: float = 120.0
    volc_asr_max_retries: int = 3
    volc_asr_max_file_mb: int = 200
    volc_asr_flash_max_mb: int = 8  # auto: short clips use flash first
    # Before MEDIA/AV briefs: yt-dlp subtitle enrich for video items lacking content
    brief_auto_enrich_media: bool = True
    brief_enrich_max_items: int = 8

    # Paper PDF download + document parse (MinerU Cloud / Kimi file-extract)
    enable_paper_parse: bool = True
    paper_parse_providers: str = "mineru,kimi"  # order for load-balance / failover
    paper_parse_strategy: str = "round_robin"  # round_robin | failover
    paper_parse_timeout_sec: int = 300
    enable_mineru: bool = True
    mineru_api_token: str = ""
    mineru_model_version: str = "vlm"
    enable_kimi_files: bool = True
    kimi_api_key: str = ""  # empty → reuse LLM_API_KEY when provider is moonshot
    kimi_files_base_url: str = ""  # empty → moonshot / llm base

    # Gewe WeChat bridge
    enable_wechat: bool = False
    gewe_enabled: bool = False
    gewe_base_url: str = "http://api.geweapi.com/gewe/v2/api"
    gewe_token: str = ""
    gewe_app_id: str = ""
    gewe_callback_url: str = "http://127.0.0.1:8000/api/wechat/webhook"
    gewe_keywords: str = "大模型,AI,Agent"

    unpaywall_email: str = "bagel@localhost"

    # Archify — GitHub learn architecture diagrams (third_party clone, Node CLI)
    enable_archify: bool = True
    archify_path: str = "./third_party/archify"
    archify_auto_setup: bool = True
    archify_git_url: str = ""
    archify_git_ref: str = "main"
    enable_github_learn: bool = True
    github_learn_max_files: int = 80
    github_learn_max_snippets: int = 24
    github_learn_snippet_chars: int = 4000
    github_learn_snippet_total_chars: int = 48000
    github_learn_timeout_sec: int = 900

    # Paths
    data_dir: str = Field(default="data")

    @field_validator("storage_backend", mode="before")
    @classmethod
    def _normalize_backend(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @property
    def resolved_database_url(self) -> str:
        """Pick SQLAlchemy URL from STORAGE_BACKEND + DATABASE_URL."""
        url = (self.database_url or "").strip()
        if self.storage_backend == StorageBackend.POSTGRES:
            if url.startswith("postgresql"):
                return url
            return "postgresql+psycopg://bagel:bagel@127.0.0.1:5432/bagel"
        # sqlite default
        if url.startswith("sqlite"):
            return url
        return DEFAULT_SQLITE_URL

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def llm_active(self) -> bool:
        return bool(
            self.llm_enabled
            and self.enable_llm_summary
            and (self.llm_base_url or "").strip()
            and (self.llm_model or "").strip()
        )

    @property
    def media_active(self) -> bool:
        return bool(self.enable_media_crawler or self.media_crawler_enabled)

    @property
    def ytdlp_active(self) -> bool:
        return bool(self.enable_ytdlp or self.ytdlp_enabled)

    @property
    def wechat_active(self) -> bool:
        return bool(self.enable_wechat or self.gewe_enabled)

    @property
    def media_platform_list(self) -> list[str]:
        return [p.strip() for p in self.media_crawler_platforms.split(",") if p.strip()]

    @property
    def media_keyword_list(self) -> list[str]:
        return [k.strip() for k in self.media_crawler_keywords.split(",") if k.strip()]

    @property
    def gewe_keyword_list(self) -> list[str]:
        return [k.strip() for k in self.gewe_keywords.split(",") if k.strip()]

    @property
    def wiki_path(self) -> Path:
        return Path(self.wiki_dir)

    @property
    def proxy_url(self) -> str | None:
        return self.https_proxy or self.http_proxy or self.all_proxy or None

    @property
    def is_dev(self) -> bool:
        return self.app_env.lower() in {"dev", "development", "local"}


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — call ``cache_clear()`` after writing `.env`."""
    return Settings()
