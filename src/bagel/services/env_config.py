"""Read / write public-facing .env keys for Settings → 配置 UI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from bagel.settings import get_settings

FieldType = Literal["bool", "str", "int", "secret", "select"]


@dataclass(frozen=True)
class EnvField:
    key: str
    label: str
    group: str
    type: FieldType = "str"
    help: str = ""
    options: tuple[str, ...] = ()
    restart_hint: bool = False


# Only expose operational knobs — secrets are editable but masked in UI.
ENV_CATALOG: tuple[EnvField, ...] = (
    EnvField("APP_ENV", "运行环境", "应用", "select", "dev / production", ("dev", "production", "local"), True),
    EnvField("APP_HOST", "监听地址", "应用", "str", restart_hint=True),
    EnvField("APP_PORT", "端口", "应用", "int", restart_hint=True),
    EnvField("LOG_LEVEL", "日志级别", "应用", "select", options=("DEBUG", "INFO", "WARNING", "ERROR"), restart_hint=True),
    EnvField("AUTH_REQUIRED", "需要登录", "应用", "bool"),
    EnvField("SESSION_SECRET", "Session 密钥", "应用", "secret", "生产环境务必修改", restart_hint=True),
    EnvField("STORAGE_BACKEND", "存储后端", "存储", "select", options=("sqlite", "postgres"), restart_hint=True),
    EnvField("DATABASE_URL", "数据库 URL", "存储", "str", restart_hint=True),
    EnvField("WIKI_ENABLED", "启用 Wiki 导出", "存储", "bool"),
    EnvField("WIKI_DIR", "Wiki 目录", "存储", "str"),
    EnvField("ENABLE_GITHUB", "启用 GitHub 采集", "功能开关", "bool"),
    EnvField("ENABLE_OVERSEAS_SOURCES", "启用海外源", "功能开关", "bool"),
    EnvField("ENABLE_LLM_SUMMARY", "启用 LLM 摘要", "功能开关", "bool"),
    EnvField("ENABLE_SCHEDULER", "默认启用定时任务", "功能开关", "bool", "也可在「定时任务」页覆盖", restart_hint=True),
    EnvField("SCHEDULER_JITTER_SECONDS", "默认抖动秒数", "功能开关", "int"),
    EnvField("COLLECT_LOOKBACK_DAYS", "采集回溯天数", "功能开关", "int"),
    EnvField(
        "NEWS_SOURCE_SLEEP_SEC",
        "新闻源间休眠秒",
        "功能开关",
        "str",
        "串行采集；源与源之间休眠，降低海外 429（可写小数如 1.5）",
    ),
    EnvField(
        "NEWS_REDDIT_SLEEP_SEC",
        "Reddit 源间休眠秒",
        "功能开关",
        "str",
        "Reddit 专用更长间隔",
    ),
    EnvField(
        "NEWS_RATE_LIMIT_COOLDOWN_SEC",
        "新闻限流冷却秒",
        "功能开关",
        "str",
        "命中 429 后整段冷却再继续下一源",
    ),
    EnvField(
        "NEWS_SOURCE_MAX_ATTEMPTS",
        "新闻单源最大尝试次数",
        "功能开关",
        "int",
        "默认 2；少重试减轻上游压力",
    ),
    EnvField("ENABLE_STOCK_ENRICHMENT", "股票 enrichment", "股票", "bool"),
    EnvField("ENABLE_STOCK_MARKET_DATA", "股票行情可视化", "股票", "bool"),
    EnvField("ENABLE_STOCK_RESEARCH_DRAFT", "股票行研草稿", "股票", "bool"),
    EnvField("STOCK_MARKET_LOOKBACK_DAYS", "股票时间线天数", "股票", "int"),
    EnvField("LLM_ENABLED", "启用 LLM 客户端", "LLM", "bool"),
    EnvField("LLM_PROVIDER", "LLM 提供商", "LLM", "str"),
    EnvField("LLM_BASE_URL", "LLM Base URL", "LLM", "str"),
    EnvField("LLM_API_KEY", "LLM API Key", "LLM", "secret"),
    EnvField("LLM_MODEL", "LLM 模型 / 接入点", "LLM", "str"),
    EnvField("LLM_TIMEOUT_SECONDS", "LLM 超时秒", "LLM", "int"),
    EnvField("GITHUB_TOKEN", "GitHub Token", "GitHub", "secret"),
    EnvField(
        "NETWORK_MODE",
        "网络模式",
        "网络",
        "select",
        "AUTO：本机直连失败再走代理；PROXY：强制代理；DIRECT：始终本机 IP。"
        "作用于全部外网能力（新闻/论文/公众号拉取等），非仅某一页。",
        ("AUTO", "DIRECT", "PROXY"),
    ),
    EnvField(
        "HTTP_PROXY",
        "HTTP 代理",
        "网络",
        "str",
        "例 http://127.0.0.1:7890。未配置则走本机 IP（云厂商 IP 易被媒体源限制时可填）",
    ),
    EnvField("HTTPS_PROXY", "HTTPS 代理", "网络", "str", "优先于 HTTP；留空则复用 HTTP 代理"),
    EnvField("ALL_PROXY", "ALL 代理", "网络", "str", "socks5://… 等统一出口，可选"),
    EnvField("NO_PROXY", "NO_PROXY", "网络", "str", "不走代理的主机，逗号分隔"),
    EnvField("RSSHUB_BASE_URL", "RSSHub 地址", "内部服务", "str"),
    EnvField(
        "ENABLE_WEWE_RSS",
        "启用 WeWe-RSS",
        "内部服务",
        "bool",
        "公众号近期文章；bagel dev 可自动 clone + 启动 sidecar",
    ),
    EnvField(
        "WEWE_RSS_AUTO_SETUP",
        "WeWe 自动 clone",
        "内部服务",
        "bool",
        "缺失时 clone 到 third_party/wewe-rss（不入库）",
    ),
    EnvField(
        "WEWE_RSS_AUTO_START",
        "WeWe 随 bagel dev 启动",
        "内部服务",
        "bool",
        "优先 Docker 镜像 cooderl/wewe-rss-sqlite；无 Docker 再试本地 Node",
    ),
    EnvField("WEWE_RSS_PATH", "WeWe 本地路径", "内部服务", "str"),
    EnvField("WEWE_RSS_GIT_URL", "WeWe Git 镜像", "内部服务", "str"),
    EnvField("WEWE_RSS_PORT", "WeWe 端口", "内部服务", "int", "默认 4000"),
    EnvField(
        "WEWE_RSS_BASE_URL",
        "WeWe-RSS 地址",
        "内部服务",
        "str",
        "留空则自动用 http://127.0.0.1:端口（sidecar 启动后）",
    ),
    EnvField(
        "WEWE_RSS_AUTH_CODE",
        "WeWe-RSS 授权码",
        "内部服务",
        "secret",
        "默认 bagel-wewe；对应容器 AUTH_CODE",
    ),
    EnvField(
        "WEWE_RSS_RUNTIME",
        "WeWe 运行时",
        "内部服务",
        "str",
        "auto / docker / local / off",
    ),
    EnvField(
        "WECHAT_MP_ENABLE_SOGOU",
        "公众号启用搜狗兜底",
        "微信",
        "bool",
        "默认关。搜狗索引少且偏旧",
    ),
    EnvField("ENABLE_MEDIA_CRAWLER", "启用自媒体", "自媒体", "bool"),
    EnvField("MEDIA_CRAWLER_PATH", "MediaCrawler 路径", "自媒体", "str"),
    EnvField("MEDIA_CRAWLER_PLATFORMS", "平台列表", "自媒体", "str", "逗号分隔，如 xhs"),
    EnvField("MEDIA_CRAWLER_KEYWORDS", "关键词", "自媒体", "str"),
    EnvField("MEDIA_CRAWLER_MAX_NOTES", "每次最大笔记数", "自媒体", "int"),
    EnvField(
        "MEDIA_CRAWLER_GET_COMMENTS",
        "抓取评论",
        "自媒体",
        "bool",
        "默认关；开后更慢、更易风控。扫码在弹出的 Chrome 窗口，建议每次 1 平台 1 关键词",
    ),
    EnvField(
        "MEDIA_CRAWLER_GET_SUB_COMMENTS",
        "抓取子评论",
        "自媒体",
        "bool",
        "需同时开「抓取评论」；默认关",
    ),
    EnvField(
        "MEDIA_CRAWLER_GET_MEDIAS",
        "MediaCrawler 下载媒体",
        "自媒体",
        "bool",
        "默认关；视频文稿请用音视频页 yt-dlp",
    ),
    EnvField("ENABLE_YTDLP", "启用音视频", "音视频", "bool"),
    EnvField("YTDLP_PATH", "yt-dlp 路径", "音视频", "str"),
    EnvField("YTDLP_GIT_URL", "yt-dlp 镜像 URL", "音视频", "str"),
    EnvField("YTDLP_GIT_REF", "yt-dlp 版本 tag", "音视频", "str"),
    EnvField("AV_MAX_ITEMS_PER_SOURCE", "每源最大条目", "音视频", "int"),
    EnvField(
        "AV_COOKIES_FROM_BROWSER",
        "浏览器 Cookie",
        "音视频",
        "str",
        "抖音/B 站下载或提文稿前：用该浏览器打开并登录站点后关闭浏览器再操作。常见值 edge",
    ),
    EnvField("AV_BILIBILI_BROWSER", "B站 Cookie 浏览器", "音视频", "str", "edge / chrome；空则复用上方 Cookie 浏览器"),
    EnvField("AV_SCAN_TIMEOUT_SEC", "单源扫描超时秒", "音视频", "int"),
    EnvField(
        "AV_DEFAULT_AUDIO_ONLY",
        "下载默认仅音频",
        "音视频",
        "bool",
        "默认关=下视频；仅需音频时开启",
    ),
    EnvField("FFMPEG_PATH", "ffmpeg 路径", "音视频", "str"),
    EnvField(
        "AV_ASR_ENABLED",
        "启用 ASR 文稿",
        "音视频ASR",
        "bool",
        "无 CC/烧录字幕时对本地音轨语音识别",
    ),
    EnvField(
        "AV_ASR_BACKEND",
        "ASR 后端",
        "音视频ASR",
        "select",
        "auto 优先火山，再 OpenAI Whisper / faster-whisper",
        ("auto", "volcengine", "openai", "faster_whisper", "off"),
    ),
    EnvField("AV_ASR_LANGUAGE", "ASR 语言", "音视频ASR", "str", "zh / en / zh-CN"),
    EnvField(
        "AV_FALLBACK_AUTHOR_DESC",
        "回退作者简介",
        "音视频ASR",
        "bool",
        "作者简介≠画面字幕；默认关",
    ),
    EnvField(
        "VOLC_ASR_API_KEY",
        "openspeech API Key",
        "音视频ASR",
        "secret",
        "豆包语音新版控制台 X-Api-Key；与下方 APP ID+Token 二选一",
    ),
    EnvField(
        "VOLC_ASR_APP_ID",
        "openspeech App ID",
        "音视频ASR",
        "str",
        "豆包语音旧版 APP ID（X-Api-App-Key）",
    ),
    EnvField(
        "VOLC_ASR_ACCESS_KEY",
        "openspeech Access Token",
        "音视频ASR",
        "secret",
        "豆包语音旧版 Access Token（X-Api-Access-Key）",
    ),
    EnvField(
        "VOLC_ASR_RESOURCE_ID",
        "openspeech Resource Id",
        "音视频ASR",
        "str",
        "默认 volc.seedasr.auc（录音文件识别 2.0）",
    ),
    EnvField(
        "VOLC_ASR_MODE",
        "openspeech 识别模式",
        "音视频ASR",
        "select",
        "auto：短音频极速版，长音频 submit/query",
        ("auto", "async", "flash"),
    ),
    EnvField("VOLC_ASR_POLL_TIMEOUT_SEC", "openspeech 轮询超时秒", "音视频ASR", "str", "长视频建议 600–1800"),
    EnvField("VOLC_ASR_MAX_RETRIES", "openspeech 提交重试次数", "音视频ASR", "int"),
    EnvField(
        "BRIEF_AUTO_ENRICH_MEDIA",
        "汇总前自动提文稿",
        "音视频",
        "bool",
        "自媒体/音视频周月报生成前，用 yt-dlp 提取字幕写入正文",
    ),
    EnvField("BRIEF_ENRICH_MAX_ITEMS", "汇总提文稿上限", "音视频", "int"),
    EnvField("ENABLE_PAPER_PARSE", "启用论文 PDF 解析", "论文", "bool"),
    EnvField(
        "PAPER_PARSE_PROVIDERS",
        "解析后端顺序",
        "论文",
        "str",
        "逗号分隔：mineru,kimi（负载+故障转移）",
    ),
    EnvField(
        "PAPER_PARSE_STRATEGY",
        "负载策略",
        "论文",
        "select",
        options=("round_robin", "failover"),
    ),
    EnvField("PAPER_PARSE_TIMEOUT_SEC", "解析超时秒", "论文", "int"),
    EnvField("ENABLE_MINERU", "启用 MinerU Cloud", "论文", "bool"),
    EnvField("MINERU_API_TOKEN", "MinerU Token", "论文", "secret"),
    EnvField("MINERU_MODEL_VERSION", "MinerU 模型", "论文", "str", "vlm / pipeline"),
    EnvField("ENABLE_KIMI_FILES", "启用 Kimi 文件抽取", "论文", "bool"),
    EnvField("KIMI_API_KEY", "Kimi API Key", "论文", "secret", "空则复用 moonshot 的 LLM_API_KEY"),
    EnvField("KIMI_FILES_BASE_URL", "Kimi Files Base URL", "论文", "str"),
    EnvField("UNPAYWALL_EMAIL", "Unpaywall 联系邮箱", "论文", "str", "DOI 查 OA PDF 用"),
    EnvField("ENABLE_ARCHIFY", "启用 Archify", "GitHub学习", "bool"),
    EnvField("ARCHIFY_AUTO_SETUP", "启动时自动安装 Archify", "GitHub学习", "bool"),
    EnvField("ARCHIFY_PATH", "Archify 路径", "GitHub学习", "str"),
    EnvField("ARCHIFY_GIT_REF", "Archify git ref", "GitHub学习", "str"),
    EnvField("ENABLE_GITHUB_LEARN", "启用项目学习页", "GitHub学习", "bool"),
    EnvField("GITHUB_LEARN_MAX_FILES", "学习页扫描文件上限", "GitHub学习", "int"),
    EnvField("GITHUB_LEARN_MAX_SNIPPETS", "学习页源码片段数", "GitHub学习", "int"),
    EnvField("GITHUB_LEARN_SNIPPET_CHARS", "单文件片段字数", "GitHub学习", "int"),
    EnvField(
        "ENABLE_WECHAT",
        "启用微信消息",
        "微信",
        "bool",
        "个人微信经 Gewe Webhook 入库；公众号文章拉取不依赖此项",
    ),
    EnvField("GEWE_BASE_URL", "Gewe API", "微信", "str"),
    EnvField("GEWE_TOKEN", "Gewe Token", "微信", "secret", "仅放此处或 .env，勿写进列表页"),
    EnvField("GEWE_APP_ID", "Gewe AppId", "微信", "str"),
    EnvField("GEWE_KEYWORDS", "微信消息关键词", "微信", "str", "逗号分隔；空=接收全部命中消息"),
    EnvField("ENABLE_FEISHU_CLI", "默认启用飞书", "飞书", "bool", "也可在 CLI 页覆盖"),
    EnvField("FEISHU_CLI_BIN", "飞书 CLI 路径", "飞书", "str"),
    EnvField("FEISHU_WEBHOOK_URL", "飞书 Webhook", "飞书", "secret"),
    EnvField(
        "FEISHU_APP_ID",
        "飞书应用 App ID",
        "飞书",
        "str",
        "企业自建应用 · 场景1收消息",
        restart_hint=True,
    ),
    EnvField(
        "FEISHU_APP_SECRET",
        "飞书应用 Secret",
        "飞书",
        "secret",
        "企业自建应用",
        restart_hint=True,
    ),
    EnvField(
        "FEISHU_VERIFICATION_TOKEN",
        "事件 Verification Token",
        "飞书",
        "secret",
        restart_hint=True,
    ),
    EnvField(
        "FEISHU_ENCRYPT_KEY",
        "事件 Encrypt Key",
        "飞书",
        "secret",
        "可留空（关闭加密）",
        restart_hint=True,
    ),
)

# Settings → 配置：一级分类 → 二级分组（ENV_CATALOG.group）
CONFIG_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("基础", ("应用", "存储", "功能开关")),
    ("网络", ("网络", "内部服务")),
    ("采集", ("自媒体", "音视频", "音视频ASR", "论文", "股票", "GitHub")),
    ("学习", ("GitHub学习",)),
    ("AI 与推送", ("LLM", "微信", "飞书")),
)


def config_family_for_group(group: str) -> str:
    for family, groups in CONFIG_FAMILIES:
        if group in groups:
            return family
    return "基础"


def resolve_config_nav(
    groups: list[dict[str, Any]],
    *,
    family: str | None = None,
    group: str | None = None,
) -> dict[str, Any]:
    """Pick active family/group for the three-pane config UI."""
    available = [g["group"] for g in groups if g.get("fields")]
    if not available:
        return {
            "families": [],
            "active_family": "",
            "subgroups": [],
            "active_group": "",
            "active_fields": [],
        }
    family_map = {name: list(gs) for name, gs in CONFIG_FAMILIES}
    # Drop empty subgroups; keep family order
    families: list[str] = []
    for name, gs in CONFIG_FAMILIES:
        present = [g for g in gs if g in available]
        if present:
            families.append(name)
            family_map[name] = present
    # Orphan groups (if any) land under 基础
    known = {g for _, gs in CONFIG_FAMILIES for g in gs}
    orphans = [g for g in available if g not in known]
    if orphans:
        if "基础" not in families:
            families.insert(0, "基础")
        family_map.setdefault("基础", [])
        family_map["基础"] = list(dict.fromkeys([*family_map.get("基础", []), *orphans]))

    active_family = family if family in families else families[0]
    subgroups = family_map.get(active_family) or available
    active_group = group if group in subgroups else subgroups[0]
    active_fields: list[dict[str, Any]] = []
    for g in groups:
        if g["group"] == active_group:
            active_fields = g["fields"]
            break
    return {
        "families": families,
        "active_family": active_family,
        "subgroups": subgroups,
        "active_group": active_group,
        "active_fields": active_fields,
    }


_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


class EnvConfigError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def resolve_env_path() -> Path:
    settings = get_settings()
    # Prefer explicit data_dir sibling project .env via cwd, then package root.
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[3] / ".env",
        Path(settings.data_dir).resolve().parent / ".env",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return Path.cwd() / ".env"


def read_env_map(path: Path | None = None) -> dict[str, str]:
    path = path or resolve_env_path()
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        values[key] = val
    return values


def current_settings_fallback() -> dict[str, str]:
    """Fill missing catalog keys from live Settings (env / defaults)."""
    s = get_settings()
    out: dict[str, str] = {}
    mapping = {
        "APP_ENV": s.app_env,
        "APP_HOST": s.app_host,
        "APP_PORT": str(s.app_port),
        "LOG_LEVEL": s.log_level,
        "AUTH_REQUIRED": str(s.auth_required).lower(),
        "SESSION_SECRET": s.session_secret,
        "STORAGE_BACKEND": s.storage_backend.value,
        "DATABASE_URL": s.database_url,
        "WIKI_ENABLED": str(s.wiki_enabled).lower(),
        "WIKI_DIR": s.wiki_dir,
        "ENABLE_GITHUB": str(s.enable_github).lower(),
        "ENABLE_OVERSEAS_SOURCES": str(s.enable_overseas_sources).lower(),
        "ENABLE_LLM_SUMMARY": str(s.enable_llm_summary).lower(),
        "ENABLE_SCHEDULER": str(s.enable_scheduler).lower(),
        "SCHEDULER_JITTER_SECONDS": str(s.scheduler_jitter_seconds),
        "COLLECT_LOOKBACK_DAYS": str(s.collect_lookback_days),
        "NEWS_SOURCE_SLEEP_SEC": str(s.news_source_sleep_sec),
        "NEWS_REDDIT_SLEEP_SEC": str(s.news_reddit_sleep_sec),
        "NEWS_RATE_LIMIT_COOLDOWN_SEC": str(s.news_rate_limit_cooldown_sec),
        "NEWS_SOURCE_MAX_ATTEMPTS": str(s.news_source_max_attempts),
        "ENABLE_STOCK_ENRICHMENT": str(s.enable_stock_enrichment).lower(),
        "ENABLE_STOCK_MARKET_DATA": str(s.enable_stock_market_data).lower(),
        "ENABLE_STOCK_RESEARCH_DRAFT": str(s.enable_stock_research_draft).lower(),
        "STOCK_MARKET_LOOKBACK_DAYS": str(s.stock_market_lookback_days),
        "LLM_ENABLED": str(s.llm_enabled).lower(),
        "LLM_PROVIDER": s.llm_provider,
        "LLM_BASE_URL": s.llm_base_url,
        "LLM_API_KEY": s.llm_api_key,
        "LLM_MODEL": s.llm_model,
        "LLM_TIMEOUT_SECONDS": str(s.llm_timeout_seconds),
        "GITHUB_TOKEN": s.github_token,
        "NETWORK_MODE": s.network_mode.value,
        "HTTP_PROXY": s.http_proxy,
        "HTTPS_PROXY": s.https_proxy,
        "ALL_PROXY": s.all_proxy,
        "NO_PROXY": s.no_proxy,
        "RSSHUB_BASE_URL": s.rsshub_base_url,
        "ENABLE_WEWE_RSS": str(s.enable_wewe_rss).lower(),
        "WEWE_RSS_AUTO_SETUP": str(s.wewe_rss_auto_setup).lower(),
        "WEWE_RSS_AUTO_START": str(s.wewe_rss_auto_start).lower(),
        "WEWE_RSS_PATH": s.wewe_rss_path,
        "WEWE_RSS_GIT_URL": s.wewe_rss_git_url,
        "WEWE_RSS_PORT": str(s.wewe_rss_port),
        "WEWE_RSS_BASE_URL": s.wewe_rss_base_url,
        "WEWE_RSS_AUTH_CODE": s.wewe_rss_auth_code,
        "WEWE_RSS_RUNTIME": s.wewe_rss_runtime,
        "WECHAT_MP_ENABLE_SOGOU": str(s.wechat_mp_enable_sogou).lower(),
        "ENABLE_MEDIA_CRAWLER": str(s.enable_media_crawler).lower(),
        "MEDIA_CRAWLER_PATH": s.media_crawler_path,
        "MEDIA_CRAWLER_PLATFORMS": s.media_crawler_platforms,
        "MEDIA_CRAWLER_KEYWORDS": s.media_crawler_keywords,
        "MEDIA_CRAWLER_MAX_NOTES": str(s.media_crawler_max_notes),
        "MEDIA_CRAWLER_GET_COMMENTS": str(s.media_crawler_get_comments).lower(),
        "MEDIA_CRAWLER_GET_SUB_COMMENTS": str(s.media_crawler_get_sub_comments).lower(),
        "MEDIA_CRAWLER_GET_MEDIAS": str(s.media_crawler_get_medias).lower(),
        "ENABLE_YTDLP": str(s.enable_ytdlp).lower(),
        "YTDLP_PATH": s.ytdlp_path,
        "YTDLP_AUTO_SETUP": str(s.ytdlp_auto_setup).lower(),
        "YTDLP_GIT_URL": s.ytdlp_git_url,
        "YTDLP_GIT_REF": s.ytdlp_git_ref,
        "AV_MAX_ITEMS_PER_SOURCE": str(s.av_max_items_per_source),
        "AV_DEFAULT_AUDIO_ONLY": str(s.av_default_audio_only).lower(),
        "AV_BILIBILI_BROWSER": s.av_bilibili_browser,
        "AV_SCAN_TIMEOUT_SEC": str(s.av_scan_timeout_sec),
        "FFMPEG_PATH": s.ffmpeg_path,
        "BRIEF_AUTO_ENRICH_MEDIA": str(s.brief_auto_enrich_media).lower(),
        "BRIEF_ENRICH_MAX_ITEMS": str(s.brief_enrich_max_items),
        "ENABLE_PAPER_PARSE": str(s.enable_paper_parse).lower(),
        "PAPER_PARSE_PROVIDERS": s.paper_parse_providers,
        "PAPER_PARSE_STRATEGY": s.paper_parse_strategy,
        "PAPER_PARSE_TIMEOUT_SEC": str(s.paper_parse_timeout_sec),
        "ENABLE_MINERU": str(s.enable_mineru).lower(),
        "MINERU_API_TOKEN": s.mineru_api_token,
        "MINERU_MODEL_VERSION": s.mineru_model_version,
        "ENABLE_KIMI_FILES": str(s.enable_kimi_files).lower(),
        "KIMI_API_KEY": s.kimi_api_key,
        "KIMI_FILES_BASE_URL": s.kimi_files_base_url,
        "UNPAYWALL_EMAIL": s.unpaywall_email,
        "ENABLE_ARCHIFY": str(s.enable_archify).lower(),
        "ARCHIFY_PATH": s.archify_path,
        "ARCHIFY_AUTO_SETUP": str(s.archify_auto_setup).lower(),
        "ARCHIFY_GIT_URL": s.archify_git_url,
        "ARCHIFY_GIT_REF": s.archify_git_ref,
        "ENABLE_GITHUB_LEARN": str(s.enable_github_learn).lower(),
        "GITHUB_LEARN_MAX_FILES": str(s.github_learn_max_files),
        "GITHUB_LEARN_MAX_SNIPPETS": str(s.github_learn_max_snippets),
        "GITHUB_LEARN_SNIPPET_CHARS": str(s.github_learn_snippet_chars),
        "ENABLE_WECHAT": str(s.enable_wechat).lower(),
        "GEWE_BASE_URL": s.gewe_base_url,
        "GEWE_TOKEN": s.gewe_token,
        "GEWE_APP_ID": s.gewe_app_id,
        "GEWE_KEYWORDS": s.gewe_keywords,
        "ENABLE_FEISHU_CLI": str(s.enable_feishu_cli).lower(),
        "FEISHU_CLI_BIN": s.feishu_cli_bin,
        "FEISHU_WEBHOOK_URL": s.feishu_webhook_url,
        "FEISHU_APP_ID": s.feishu_app_id,
        "FEISHU_APP_SECRET": s.feishu_app_secret,
        "FEISHU_VERIFICATION_TOKEN": s.feishu_verification_token,
        "FEISHU_ENCRYPT_KEY": s.feishu_encrypt_key,
    }
    for k, v in mapping.items():
        out[k] = "" if v is None else str(v)
    return out


def catalog_for_ui() -> list[dict[str, Any]]:
    from bagel.pipeline.paths import portable_env_value

    file_vals = read_env_map()
    fallback = current_settings_fallback()
    groups: dict[str, list[dict[str, Any]]] = {}
    for field in ENV_CATALOG:
        raw = file_vals.get(field.key)
        if raw is None:
            raw = fallback.get(field.key, "")
        # Never show machine-absolute dirs/paths in the config form
        if field.type != "secret" and raw:
            raw = portable_env_value(field.key, raw)
        display = raw
        if field.type == "secret" and raw:
            display = _mask(raw)
        groups.setdefault(field.group, []).append(
            {
                "key": field.key,
                "label": field.label,
                "type": field.type,
                "help": field.help,
                "options": list(field.options),
                "restart_hint": field.restart_hint,
                "value": raw,
                "display": display,
                "has_secret": bool(field.type == "secret" and raw),
            }
        )
    return [{"group": g, "fields": fields} for g, fields in groups.items()]


def update_env_values(updates: dict[str, str], *, path: Path | None = None) -> Path:
    from bagel.pipeline.paths import portable_env_value

    path = path or resolve_env_path()
    allowed = {f.key: f for f in ENV_CATALOG}
    cleaned: dict[str, str] = {}
    for key, value in updates.items():
        field = allowed.get(key)
        if field is None:
            continue
        text = (value if value is not None else "").strip()
        # Keep existing secret when UI posts masked placeholder
        if field.type == "secret" and (not text or text == _mask(read_env_map(path).get(key, ""))):
            existing = read_env_map(path).get(key)
            if existing is None:
                existing = current_settings_fallback().get(key, "")
            if text.startswith("••••") or text == _mask(existing):
                continue
        if field.type == "bool":
            text = "true" if text.lower() in {"1", "true", "on", "yes"} else "false"
        elif field.type == "int":
            if text == "":
                continue
            try:
                int(text)
            except ValueError as exc:
                raise EnvConfigError(f"{key} 必须是整数") from exc
        elif field.type == "select" and field.options and text and text not in field.options:
            raise EnvConfigError(f"{key} 必须是 {', '.join(field.options)} 之一")
        cleaned[key] = portable_env_value(key, text) if text else text

    if not cleaned:
        return path

    if path.exists():
        original = path.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
    else:
        lines = ["# Generated by Bagel Settings → 配置\n"]

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        m = _LINE_RE.match(stripped) if stripped and not stripped.startswith("#") else None
        if m and m.group(1) in cleaned:
            key = m.group(1)
            new_lines.append(f"{key}={_format_value(cleaned[key])}\n")
            seen.add(key)
        else:
            new_lines.append(line if line.endswith("\n") else line + "\n")

    missing = [k for k in cleaned if k not in seen]
    if missing:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        new_lines.append("\n# --- updated via Settings UI ---\n")
        for key in missing:
            new_lines.append(f"{key}={_format_value(cleaned[key])}\n")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(new_lines), encoding="utf-8")
    get_settings.cache_clear()
    return path


def _format_value(value: str) -> str:
    if any(ch in value for ch in ' \t#"\'\\'):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]
