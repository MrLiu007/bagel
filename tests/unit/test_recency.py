"""Recency window helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bagel.pipeline.recency import (
    github_query_with_recency,
    is_within_lookback,
    lookback_cutoff,
)


def test_lookback_keeps_recent_only() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    recent = now - timedelta(days=3)
    old = now - timedelta(days=30)
    assert is_within_lookback(recent, days=14, now=now) is True
    assert is_within_lookback(old, days=14, now=now) is False
    assert is_within_lookback(None, days=14, now=now, keep_unknown=False) is False
    assert is_within_lookback(None, days=14, now=now, keep_unknown=True) is True


def test_github_query_appends_pushed_filter() -> None:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    q = github_query_with_recency("llm stars:>50", days=14, now=now)
    assert q == "llm stars:>50 pushed:>2026-08-16"
    # Must not wrap in parentheses — GitHub Search returns 422 for many "(q) pushed:>" forms.
    assert not q.startswith("(")
    # idempotent when already dated
    assert github_query_with_recency(q, days=14, now=now) == q
    assert lookback_cutoff(14, now=now).day == 16
