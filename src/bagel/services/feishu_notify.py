"""Async Feishu notifications after scheduled collect jobs."""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


def maybe_push_after_collect(job_name: str, result: Any) -> None:
    """Best-effort background push when runtime flag is on. Never raises to caller."""
    try:
        from bagel.services.runtime_config import load_runtime_config

        cfg = load_runtime_config()
        if not cfg.feishu_push_after_collect or not cfg.enable_feishu_cli:
            return
        if not cfg.feishu_webhook_url and not cfg.enable_feishu_cli:
            return
    except Exception:  # noqa: BLE001
        logger.exception("feishu.notify.config_failed")
        return

    if job_name not in {
        "collect_news",
        "collect_github",
        "collect_stocks",
        "build_digest",
    }:
        return

    threading.Thread(
        target=_push_job_summary,
        args=(job_name, result),
        name=f"feishu-push-{job_name}",
        daemon=True,
    ).start()


def _push_job_summary(job_name: str, result: Any) -> None:
    try:
        from bagel.integrations import feishu_cli

        text = format_collect_push(job_name, result)
        if not text:
            return
        r = feishu_cli.send_text(text)
        if not r.ok:
            logger.warning("feishu.notify.failed job=%s err=%s", job_name, r.error or r.stderr)
        else:
            logger.info("feishu.notify.ok job=%s", job_name)
    except Exception:  # noqa: BLE001
        logger.exception("feishu.notify.exception job=%s", job_name)


def format_collect_push(job_name: str, result: Any) -> str:
    data = result if isinstance(result, dict) else {}
    labels = {
        "collect_news": "新闻采集",
        "collect_github": "GitHub 采集",
        "collect_stocks": "股票采集",
        "build_digest": "日报生成",
    }
    label = labels.get(job_name, job_name)
    status = data.get("status") or "done"
    created = data.get("items_created")
    updated = data.get("items_updated")
    found = data.get("items_found")
    lines = [f"【贝果】定时任务完成 · {label}", f"状态：{status}"]
    if created is not None:
        lines.append(f"新建：{created}")
    if updated is not None:
        lines.append(f"更新：{updated}")
    if found is not None:
        lines.append(f"发现：{found}")
    errors = data.get("errors") or []
    if errors:
        lines.append(f"告警：{len(errors)} 条（详见系统日志）")
    if job_name == "build_digest":
        lines.append("本地日报已生成；可在系统「汇总」或 CLI 推送飞书摘要。")
    else:
        lines.append("数据已入库。回复「昨日资讯」可拉取摘要。")
    return "\n".join(lines)
