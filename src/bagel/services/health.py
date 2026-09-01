"""Network probing and health checks with degraded-mode support.

Used by `bagel doctor`, `/settings/health`, and boot-time diagnostics.
Individual check failures set ``degraded`` / ``can_run`` rather than crashing
the process — overseas/GitHub outages must not block CN collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from bagel.integrations.http import build_http_client
from bagel.settings import NetworkMode, Settings, get_settings


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str = ""
    degraded: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthReport:
    checks: list[CheckResult]
    can_run: bool = True

    @property
    def all_ok(self) -> bool:
        return all(c.ok for c in self.checks)


def _probe_url(
    url: str,
    *,
    settings: Settings,
    force_proxy: bool | None = None,
    timeout: float = 8.0,
) -> tuple[bool, str, int | None]:
    try:
        with build_http_client(settings, timeout=timeout, force_proxy=force_proxy) as client:
            resp = client.get(url)
            return True, f"HTTP {resp.status_code}", resp.status_code
    except (httpx.HTTPError, OSError) as exc:
        return False, str(exc)[:200], None


def check_database(session: Session | None) -> CheckResult:
    if session is None:
        return CheckResult(name="Database", ok=False, message="No DB session", degraded=True)
    try:
        session.execute(text("SELECT 1"))
        backend = get_settings().storage_backend.value
        return CheckResult(name="Database", ok=True, message=f"connected ({backend})")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="Database",
            ok=False,
            message=str(exc)[:200],
            degraded=False,
        )


def check_rsshub(settings: Settings) -> CheckResult:
    base = settings.rsshub_base_url.rstrip("/")
    ok, msg, status = _probe_url(base + "/", settings=settings, force_proxy=False)
    if ok:
        return CheckResult(name="RSSHub", ok=True, message=msg)
    return CheckResult(name="RSSHub", ok=False, message=msg, degraded=True)


def check_freshrss(settings: Settings) -> CheckResult:
    base = settings.freshrss_base_url.rstrip("/")
    ok, msg, _ = _probe_url(base + "/", settings=settings, force_proxy=False)
    if ok:
        return CheckResult(name="FreshRSS", ok=True, message=msg)
    return CheckResult(name="FreshRSS", ok=False, message=msg, degraded=True)


def check_china_network(settings: Settings) -> CheckResult:
    ok, msg, _ = _probe_url("https://www.baidu.com", settings=settings, force_proxy=False)
    if ok:
        return CheckResult(name="China Network", ok=True, message=msg)
    return CheckResult(name="China Network", ok=False, message=msg, degraded=True)


def check_github(settings: Settings) -> CheckResult:
    headers_note = ""
    url = "https://api.github.com/rate_limit"
    ok, msg, status = _probe_url(url, settings=settings, force_proxy=None)
    if not ok and settings.network_mode == NetworkMode.AUTO and settings.proxy_url:
        ok2, msg2, status = _probe_url(url, settings=settings, force_proxy=True)
        if ok2:
            return CheckResult(
                name="GitHub API",
                ok=True,
                message=f"{msg2} via proxy",
                details={"proxy": True},
            )
        msg = f"{msg}; proxy retry: {msg2}"
    if ok:
        return CheckResult(name="GitHub API", ok=True, message=msg + headers_note)
    hint = ""
    if settings.proxy_url is None:
        hint = (
            " If you use a local proxy: "
            "HTTPS_PROXY=http://host.docker.internal:7890"
        )
    return CheckResult(
        name="GitHub API",
        ok=False,
        message=f"{msg}.{hint}",
        degraded=True,
        details={"status": status},
    )


def check_overseas_rss(settings: Settings) -> CheckResult:
    # Lightweight probe — OpenAI blog RSS as overseas marker.
    ok, msg, _ = _probe_url(
        "https://openai.com/blog/rss.xml",
        settings=settings,
        force_proxy=None,
        timeout=10.0,
    )
    if not ok and settings.network_mode == NetworkMode.AUTO and settings.proxy_url:
        ok, msg, _ = _probe_url(
            "https://openai.com/blog/rss.xml",
            settings=settings,
            force_proxy=True,
            timeout=10.0,
        )
        if ok:
            return CheckResult(name="Overseas RSS", ok=True, message=f"{msg} via proxy")
    if ok:
        return CheckResult(name="Overseas RSS", ok=True, message=msg)
    return CheckResult(
        name="Overseas RSS",
        ok=False,
        message=msg,
        degraded=True,
    )


def check_llm(settings: Settings) -> CheckResult:
    if not settings.llm_enabled or not settings.enable_llm_summary:
        return CheckResult(name="LLM API", ok=True, message="disabled (skipped)")
    if not settings.llm_base_url:
        return CheckResult(
            name="LLM API",
            ok=False,
            message="LLM_BASE_URL not set",
            degraded=True,
        )
    if not settings.llm_model:
        return CheckResult(
            name="LLM API",
            ok=False,
            message="LLM_MODEL not set",
            degraded=True,
        )
    base = settings.llm_base_url.rstrip("/")
    provider = (settings.llm_provider or "openai").strip().lower()
    timeout = float(getattr(settings, "llm_timeout_seconds", 180) or 180)
    headers = {}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    # Probe /models (OpenAI-compatible). Volcengine Ark / custom providers also support it.
    try:
        with build_http_client(settings, timeout=min(timeout, 20.0)) as client:
            resp = client.get(base + "/models", headers=headers)
            ok = 200 <= resp.status_code < 500
            msg = f"HTTP {resp.status_code} · provider={provider} · model={settings.llm_model}"
            if resp.status_code == 401:
                return CheckResult(name="LLM API", ok=False, message=f"{msg} (API Key 无效)", degraded=True)
            if resp.status_code >= 400:
                return CheckResult(name="LLM API", ok=False, message=msg, degraded=True)
            return CheckResult(name="LLM API", ok=ok, message=msg)
    except (httpx.HTTPError, OSError) as exc:
        return CheckResult(
            name="LLM API",
            ok=False,
            message=f"{str(exc)[:180]} · provider={provider}",
            degraded=True,
        )


def run_health_checks(session: Session | None = None, settings: Settings | None = None) -> HealthReport:
    settings = settings or get_settings()
    checks = [
        check_database(session),
        check_rsshub(settings),
        check_freshrss(settings),
        check_china_network(settings),
        check_github(settings),
        check_overseas_rss(settings),
        check_llm(settings),
    ]
    # App can run as long as the transactional DB works.
    # Spec: overseas/GitHub failure must not stop domestic collection / app boot.
    db = next(c for c in checks if c.name == "Database")
    can_run = db.ok or session is None
    return HealthReport(checks=checks, can_run=can_run)


def format_doctor_report(report: HealthReport) -> str:
    lines = ["Bagel Doctor", ""]
    for c in report.checks:
        tag = "OK" if c.ok else "WARN"
        lines.append(f"[{tag}] {c.name}")
        if c.message:
            lines.append(f"       {c.message}")
        if not c.ok and c.name == "GitHub API":
            lines.append("       GitHub collection is temporarily disabled.")
            lines.append("")
            lines.append("       If you are using a local proxy:")
            lines.append("       HTTPS_PROXY=http://host.docker.internal:7890")
    lines.append("")
    if report.can_run:
        lines.append("[OK] Application can run in degraded mode.")
    else:
        lines.append("[FAIL] Application cannot start — fix Database first.")
    return "\n".join(lines)
