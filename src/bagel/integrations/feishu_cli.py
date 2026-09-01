"""Feishu / Lark CLI adapter — first external CLI provider.

Primary: optional `lark-cli` (or custom bin) via CliRuntime.
Fallback: Feishu custom bot webhook (httpx), so messaging works without installing CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from bagel.integrations.cli_runtime import CliBinary, CliResult, resolve_binary, run_command
from bagel.integrations.http import build_http_client
from bagel.services.runtime_config import load_runtime_config
from bagel.settings import get_settings


@dataclass
class FeishuStatus:
    enabled: bool
    binary: CliBinary
    webhook_configured: bool
    ready: bool
    message: str

    def as_dict(self) -> dict[str, Any]:
        from bagel.pipeline.paths import display_path

        return {
            "enabled": self.enabled,
            "ready": self.ready,
            "message": self.message,
            "webhook_configured": self.webhook_configured,
            "cli_found": self.binary.found,
            "cli_path": display_path(self.binary.path) if self.binary.path else None,
            "cli_version": self.binary.version,
            "cli_hints": self.binary.hints,
        }


def status() -> FeishuStatus:
    cfg = load_runtime_config()
    binary = resolve_binary(cfg.feishu_cli_bin)
    webhook_ok = bool(cfg.feishu_webhook_url)
    if not cfg.enable_feishu_cli:
        return FeishuStatus(
            enabled=False,
            binary=binary,
            webhook_configured=webhook_ok,
            ready=False,
            message="飞书 CLI 集成未启用",
        )
    if binary.found or webhook_ok:
        from bagel.pipeline.paths import display_path

        parts = []
        if binary.found:
            parts.append(f"CLI 可用：{display_path(binary.path)}")
        if webhook_ok:
            parts.append("Webhook 已配置")
        return FeishuStatus(
            enabled=True,
            binary=binary,
            webhook_configured=webhook_ok,
            ready=True,
            message="；".join(parts),
        )
    return FeishuStatus(
        enabled=True,
        binary=binary,
        webhook_configured=False,
        ready=False,
        message="未找到 lark-cli，且未配置 Webhook。请安装 CLI 或填写机器人 Webhook。",
    )


def send_text(text: str) -> CliResult:
    """Send a text message via webhook (preferred if set) or `lark-cli` if available."""
    cfg = load_runtime_config()
    body = (text or "").strip()
    if not body:
        return CliResult(argv=[], returncode=1, error="empty message")
    if not cfg.enable_feishu_cli:
        return CliResult(argv=[], returncode=1, error="feishu cli disabled")

    if cfg.feishu_webhook_url:
        return _send_webhook(cfg.feishu_webhook_url, body)

    binary = resolve_binary(cfg.feishu_cli_bin)
    if not binary.found or not binary.path:
        return CliResult(
            argv=[cfg.feishu_cli_bin],
            returncode=127,
            error="lark-cli not found; configure webhook or install CLI",
        )
    # Best-effort common shapes; real lark-cli subcommands vary by version.
    return run_command(
        [binary.path, "im", "send", "--msg-type", "text", "--content", body],
        timeout=30.0,
    )


def push_digest_chunks(chunks: list[str]) -> CliResult:
    """Send one or more text chunks; stops on first failure."""
    if not chunks:
        return CliResult(argv=[], returncode=1, error="empty digest")
    last = CliResult(argv=[], returncode=1, error="no chunks sent")
    for i, chunk in enumerate(chunks, start=1):
        prefix = f"({i}/{len(chunks)})\n" if len(chunks) > 1 else ""
        last = send_text(prefix + chunk)
        if not last.ok:
            return last
    return last


def push_yesterday_digest(session, *, per_type_limit: int = 8) -> tuple[CliResult, dict]:
    from bagel.services import feishu_digest

    payload = feishu_digest.build_yesterday_digest(session, per_type_limit=per_type_limit)
    result = push_digest_chunks(payload.chunks)
    return result, {
        "title": payload.title,
        "chunks": len(payload.chunks),
        "counts": payload.section_counts,
    }


def push_week_briefs_digest(session, *, which: str = "both") -> tuple[CliResult, dict]:
    from bagel.services import feishu_digest

    payload = feishu_digest.build_week_briefs_digest(session, which=which)
    result = push_digest_chunks(payload.chunks)
    return result, {
        "title": payload.title,
        "chunks": len(payload.chunks),
        "counts": payload.section_counts,
    }


def _send_webhook(url: str, text: str) -> CliResult:
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        with build_http_client(get_settings(), timeout=20.0) as client:
            resp = client.post(url, json=payload)
            ok = resp.status_code < 400
            data = resp.text[:500]
            return CliResult(
                argv=["webhook", "POST", url.split("?")[0]],
                returncode=0 if ok else resp.status_code,
                stdout=data if ok else "",
                stderr="" if ok else data,
                error=None if ok else f"HTTP {resp.status_code}",
            )
    except (httpx.HTTPError, OSError) as exc:
        return CliResult(
            argv=["webhook", "POST"],
            returncode=1,
            error=str(exc)[:300],
        )
