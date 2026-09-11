"""Per-source fetch guard: limited retries, rate-limit backoff, then skip."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger("bagel.source_guard")

T = TypeVar("T")

MAX_SOURCE_ATTEMPTS = 3


def is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429:
        return True
    return (
        "429" in msg
        or "too many requests" in msg
        or "rate limit" in msg
        or "rate_limit" in msg
    )


def is_timeout_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return (
        "timeout" in name
        or "timed out" in msg
        or "timeout" in msg
        or "readtimeout" in name
        or "connecttimeout" in name
    )


def classify_fetch_error(exc: BaseException) -> tuple[str, str]:
    """Return (status_code_for_stats, user_facing_hint)."""
    msg = str(exc).strip() or type(exc).__name__
    if is_rate_limit_error(exc):
        return (
            "rate_limited",
            f"上游限流（429）。已按策略重试后跳过。详情：{msg[:160]}",
        )
    if is_timeout_error(exc):
        return (
            "timeout",
            f"拉取超时（已重试 {MAX_SOURCE_ATTEMPTS} 次后跳过）：{msg[:160]}",
        )
    return ("failed", msg[:220])


def raise_for_retryable_error_code(
    error_code: str | None,
    message: str | None = None,
) -> None:
    """Raise a retryable exception when collector returned RATE_LIMITED / TIMEOUT.

    Non-retryable codes are ignored so the caller can keep the CollectResult as-is.
    """
    code = (error_code or "").strip().upper()
    msg = (message or code or "error").strip()
    if code in {"RATE_LIMITED", "HTTP_429"} or "429" in msg:
        raise RuntimeError(f"429 rate limit: {msg}")
    if code in {"NETWORK_TIMEOUT", "TIMEOUT"} or "timed out" in msg.lower():
        raise TimeoutError(msg)


def fetch_source_with_retries(
    fetch_fn: Callable[[], T],
    *,
    source_name: str,
    max_attempts: int = MAX_SOURCE_ATTEMPTS,
    on_attempt: Callable[[int, int, str], None] | None = None,
) -> T:
    """Call ``fetch_fn`` up to ``max_attempts`` times; raise last error if all fail.

    - Timeout / network errors: retry with short backoff
    - Rate limit (429): sleep longer, then retry (reduces pressure)
    - Other HTTP errors: no endless hang; fail after attempts
    """
    attempts = max(1, int(max_attempts))
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            if on_attempt:
                on_attempt(attempt, attempts, f"拉取 {source_name}" + (f"（重试 {attempt}/{attempts}）" if attempt > 1 else ""))
            return fetch_fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            retryable = is_timeout_error(exc) or is_rate_limit_error(exc) or _is_transient(exc)
            logger.warning(
                "source_fetch_failed source=%s attempt=%s/%s retryable=%s err=%s",
                source_name,
                attempt,
                attempts,
                retryable,
                str(exc)[:200],
            )
            if not retryable or attempt >= attempts:
                break
            wait = _backoff_seconds(exc, attempt)
            if on_attempt:
                on_attempt(
                    attempt,
                    attempts,
                    f"{source_name} 限流/超时，休眠 {wait:.1f}s 后重试（{attempt}/{attempts}）",
                )
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def _is_transient(exc: BaseException) -> bool:
    """Connection blips only — do not retry persistent gateway 502/503/504.

    RSSHub upstream 502 rarely recovers within a few seconds; retries just burn time
    and amplify load. Callers should skip and continue other sources.
    """
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    # Explicitly exclude gateway statuses from transient retries.
    if any(code in msg for code in ("502", "503", "504", "bad gateway")):
        return False
    return any(
        x in msg or x in name
        for x in (
            "connection",
            "temporarily",
            "reset",
            "broken pipe",
            "remoteprotocol",
        )
    )


def _backoff_seconds(exc: BaseException, attempt: int) -> float:
    if is_rate_limit_error(exc):
        resp = getattr(exc, "response", None)
        header = None
        if resp is not None:
            header = (getattr(resp, "headers", None) or {}).get("Retry-After")
        if header and str(header).isdigit():
            return min(float(header), 45.0)
        # Longer sleeps between 429 retries (news job also cools down between sources).
        return min(4.0 * attempt, 24.0)
    if is_timeout_error(exc):
        return min(1.0 * attempt, 5.0)
    return min(1.2 * attempt, 6.0)


def safe_source_fetch(
    fetch_fn: Callable[[], T],
    *,
    source_name: str,
    max_attempts: int = MAX_SOURCE_ATTEMPTS,
    on_attempt: Callable[[int, int, str], None] | None = None,
) -> tuple[T | None, dict[str, Any] | None]:
    """Like ``fetch_source_with_retries`` but returns (result, error_info) instead of raising."""
    try:
        return (
            fetch_source_with_retries(
                fetch_fn,
                source_name=source_name,
                max_attempts=max_attempts,
                on_attempt=on_attempt,
            ),
            None,
        )
    except Exception as exc:  # noqa: BLE001
        status, hint = classify_fetch_error(exc)
        return None, {"status": status, "error": hint, "exc": exc}
