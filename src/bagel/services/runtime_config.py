"""Persisted runtime overrides (scheduler / CLI) under data/runtime_config.json."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from bagel.settings import get_settings

SCHEDULE_INTERVAL_OPTIONS: tuple[int, ...] = (30, 60, 120, 240, 480, 720)
DEFAULT_JITTER_SECONDS = 120

_lock = threading.RLock()


@dataclass
class RuntimeConfig:
    enable_scheduler: bool = False
    schedule_interval_minutes: int = 30
    schedule_jitter_seconds: int = DEFAULT_JITTER_SECONDS
    schedule_collect_news: bool = True
    schedule_collect_github: bool = True
    schedule_collect_stocks: bool = False
    schedule_collect_models: bool = False
    enable_keyword_growth: bool = True
    enable_wiki_compile: bool = True
    enable_feishu_cli: bool = False

    feishu_cli_bin: str = "lark-cli"
    feishu_webhook_url: str = ""
    feishu_push_after_collect: bool = False

    def normalized(self) -> RuntimeConfig:
        minutes = int(self.schedule_interval_minutes)
        if minutes not in SCHEDULE_INTERVAL_OPTIONS:
            minutes = 30
        jitter = max(0, min(600, int(self.schedule_jitter_seconds)))
        return RuntimeConfig(
            enable_scheduler=bool(self.enable_scheduler),
            schedule_interval_minutes=minutes,
            schedule_jitter_seconds=jitter,
            schedule_collect_news=bool(self.schedule_collect_news),
            schedule_collect_github=bool(self.schedule_collect_github),
            schedule_collect_stocks=bool(self.schedule_collect_stocks),
            schedule_collect_models=bool(self.schedule_collect_models),
            enable_keyword_growth=bool(self.enable_keyword_growth),
            enable_wiki_compile=bool(self.enable_wiki_compile),
            enable_feishu_cli=bool(self.enable_feishu_cli),

            feishu_cli_bin=(self.feishu_cli_bin or "lark-cli").strip() or "lark-cli",
            feishu_webhook_url=(self.feishu_webhook_url or "").strip(),
            feishu_push_after_collect=bool(self.feishu_push_after_collect),
        )


def config_path() -> Path:
    root = Path(get_settings().data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root / "runtime_config.json"


def load_runtime_config() -> RuntimeConfig:
    path = config_path()
    with _lock:
        if not path.exists():
            # Seed from env defaults once.
            settings = get_settings()
            cfg = RuntimeConfig(
                enable_scheduler=bool(getattr(settings, "enable_scheduler", False)),
                schedule_interval_minutes=int(
                    getattr(settings, "news_collect_interval_minutes", 30) or 30
                ),
                schedule_jitter_seconds=int(
                    getattr(settings, "scheduler_jitter_seconds", DEFAULT_JITTER_SECONDS)
                    or DEFAULT_JITTER_SECONDS
                ),
                enable_feishu_cli=bool(getattr(settings, "enable_feishu_cli", False)),
                feishu_cli_bin=str(getattr(settings, "feishu_cli_bin", "lark-cli") or "lark-cli"),
                feishu_webhook_url=str(getattr(settings, "feishu_webhook_url", "") or ""),
            ).normalized()
            save_runtime_config(cfg)
            return cfg
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return RuntimeConfig().normalized()
        known = {f.name for f in fields(RuntimeConfig)}
        data = {k: v for k, v in (raw or {}).items() if k in known}
        return RuntimeConfig(**data).normalized()


def save_runtime_config(cfg: RuntimeConfig) -> RuntimeConfig:
    cleaned = cfg.normalized()
    path = config_path()
    with _lock:
        path.write_text(
            json.dumps(asdict(cleaned), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return cleaned


def update_runtime_config(**kwargs: Any) -> RuntimeConfig:
    cfg = load_runtime_config()
    data = asdict(cfg)
    data.update(kwargs)
    return save_runtime_config(RuntimeConfig(**data))
