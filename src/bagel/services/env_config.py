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
    EnvField("NETWORK_MODE", "网络模式", "网络", "select", options=("AUTO", "DIRECT", "PROXY")),
    EnvField("HTTP_PROXY", "HTTP 代理", "网络", "str"),
    EnvField("HTTPS_PROXY", "HTTPS 代理", "网络", "str"),
    EnvField("ALL_PROXY", "ALL 代理", "网络", "str"),
    EnvField("NO_PROXY", "NO_PROXY", "网络", "str"),
    EnvField("RSSHUB_BASE_URL", "RSSHub 地址", "内部服务", "str"),
    EnvField("ENABLE_MEDIA_CRAWLER", "启用自媒体", "自媒体", "bool"),
    EnvField("MEDIA_CRAWLER_PATH", "MediaCrawler 路径", "自媒体", "str"),
    EnvField("MEDIA_CRAWLER_PLATFORMS", "平台列表", "自媒体", "str", "逗号分隔，如 xhs"),
    EnvField("MEDIA_CRAWLER_KEYWORDS", "关键词", "自媒体", "str"),
    EnvField("MEDIA_CRAWLER_MAX_NOTES", "每次最大笔记数", "自媒体", "int"),
    EnvField("ENABLE_WECHAT", "启用微信", "微信", "bool"),
    EnvField("GEWE_BASE_URL", "Gewe API", "微信", "str"),
    EnvField("GEWE_TOKEN", "Gewe Token", "微信", "secret"),
    EnvField("GEWE_APP_ID", "Gewe AppId", "微信", "str"),
    EnvField("GEWE_KEYWORDS", "微信关键词", "微信", "str"),
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
        "ENABLE_MEDIA_CRAWLER": str(s.enable_media_crawler).lower(),
        "MEDIA_CRAWLER_PATH": s.media_crawler_path,
        "MEDIA_CRAWLER_PLATFORMS": s.media_crawler_platforms,
        "MEDIA_CRAWLER_KEYWORDS": s.media_crawler_keywords,
        "MEDIA_CRAWLER_MAX_NOTES": str(s.media_crawler_max_notes),
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
