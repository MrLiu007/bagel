"""Tests for per-source fetch guard (retry / skip / rate-limit)."""

from __future__ import annotations

import httpx
import pytest

from bagel.jobs.source_guard import (
    MAX_SOURCE_ATTEMPTS,
    classify_fetch_error,
    fetch_source_with_retries,
    is_rate_limit_error,
    is_timeout_error,
    raise_for_retryable_error_code,
    safe_source_fetch,
)


def test_classify_rate_limit_and_timeout() -> None:
    assert is_rate_limit_error(RuntimeError("429 Too Many Requests"))
    assert is_timeout_error(TimeoutError("read timed out"))
    status, hint = classify_fetch_error(TimeoutError("timed out"))
    assert status == "timeout"
    assert "跳过" in hint
    status2, hint2 = classify_fetch_error(RuntimeError("API rate limit exceeded"))
    assert status2 == "rate_limited"
    assert "限流" in hint2


def test_fetch_retries_then_raises() -> None:
    calls = {"n": 0}

    def boom() -> str:
        calls["n"] += 1
        raise TimeoutError("read timed out")

    with pytest.raises(TimeoutError):
        fetch_source_with_retries(boom, source_name="demo", max_attempts=3)
    assert calls["n"] == 3


def test_fetch_succeeds_on_second_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bagel.jobs.source_guard.time.sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow")
        return "ok"

    assert fetch_source_with_retries(flaky, source_name="demo", max_attempts=3) == "ok"
    assert calls["n"] == 2


def test_safe_source_fetch_skips_after_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bagel.jobs.source_guard.time.sleep", lambda *_a, **_k: None)

    def boom() -> None:
        raise TimeoutError("hung")

    result, err = safe_source_fetch(boom, source_name="OpenAlex", max_attempts=MAX_SOURCE_ATTEMPTS)
    assert result is None
    assert err is not None
    assert err["status"] == "timeout"


def test_raise_for_retryable_error_code() -> None:
    with pytest.raises(RuntimeError, match="429"):
        raise_for_retryable_error_code("RATE_LIMITED", "too many")
    with pytest.raises(TimeoutError):
        raise_for_retryable_error_code("NETWORK_TIMEOUT", "timed out")
    # Non-retryable: no raise
    raise_for_retryable_error_code("PARSE_ERROR", "bad xml")


def test_gateway_502_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bagel.jobs.source_guard.time.sleep", lambda *_a, **_k: None)
    calls = {"n": 0}

    def boom() -> None:
        calls["n"] += 1
        raise RuntimeError("502 Bad Gateway from rsshub")

    with pytest.raises(RuntimeError, match="502"):
        fetch_source_with_retries(boom, source_name="微博热搜", max_attempts=3)
    assert calls["n"] == 1


def test_rate_limit_backoff_longer_than_timeout() -> None:
    from bagel.jobs.source_guard import _backoff_seconds

    assert _backoff_seconds(RuntimeError("429"), 2) >= 8.0
    assert _backoff_seconds(TimeoutError("slow"), 2) <= 5.0
