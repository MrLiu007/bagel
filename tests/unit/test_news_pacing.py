"""News job pacing helpers (source sleep / Reddit gap)."""

from __future__ import annotations

from bagel.jobs.news import _is_reddit_source, _pace_before_source
from bagel.settings import Settings


def test_is_reddit_source() -> None:
    assert _is_reddit_source("https://www.reddit.com/r/MachineLearning/new/.rss")
    assert _is_reddit_source("/reddit/user/foo/submitted")
    assert not _is_reddit_source("https://openai.com/blog/rss.xml")


def test_pace_before_source_sleeps(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("bagel.jobs.news.time.sleep", lambda s: slept.append(s))
    settings = Settings(
        news_source_sleep_sec=1.5,
        news_reddit_sleep_sec=8.0,
    )
    _pace_before_source(index=1, source_url="https://a.com/feed", settings=settings, progress=None)
    assert slept == []
    _pace_before_source(
        index=2,
        source_url="https://openai.com/blog/rss.xml",
        settings=settings,
        progress=None,
    )
    assert slept == [1.5]
    slept.clear()
    _pace_before_source(
        index=3,
        source_url="https://www.reddit.com/r/MachineLearning/new/.rss",
        settings=settings,
        progress=None,
    )
    assert slept == [8.0]
