"""Phase 4: GitHub collector, queries, snapshots, releases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from bagel.collectors.github import GithubCollector
from bagel.domain.enums import ItemType, JobStatus, SourceType
from bagel.domain.models import Base, IntelGithubQuery, IntelItem
from bagel.jobs.github import run_collect_github
from bagel.storage.database import get_engine, get_session_factory
from bagel.storage.repositories import GithubSnapshotRepository
from bagel.storage.seed import DEFAULT_GITHUB_QUERIES, seed_if_empty


@pytest.fixture()
def db() -> Session:
    engine = get_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


SAMPLE_SEARCH = {
    "total_count": 1,
    "items": [
        {
            "full_name": "acme/agent-kit",
            "html_url": "https://github.com/acme/agent-kit",
            "description": "Open source AI Agent toolkit with RAG",
            "stargazers_count": 1200,
            "forks_count": 80,
            "open_issues_count": 12,
            "language": "Python",
            "topics": ["agent", "rag"],
            "license": {"spdx_id": "Apache-2.0"},
            "owner": {"login": "acme"},
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-08-30T00:00:00Z",
            "pushed_at": "2026-08-30T00:00:00Z",
        }
    ],
}

SAMPLE_RELEASE = {
    "html_url": "https://github.com/acme/agent-kit/releases/tag/v1.2.0",
    "tag_name": "v1.2.0",
    "name": "v1.2.0",
    "body": "Release notes",
    "author": {"login": "acme"},
    "published_at": "2026-08-29T00:00:00Z",
    "prerelease": False,
    "draft": False,
}


def test_seed_has_at_least_8_github_queries(db: Session) -> None:
    result = seed_if_empty(db)
    assert result["github_queries"] >= 8
    assert len(DEFAULT_GITHUB_QUERIES) >= 8
    assert db.query(IntelGithubQuery).count() >= 8


def test_snapshot_star_delta(db: Session) -> None:
    repo = GithubSnapshotRepository(db)
    older = repo.record(repo_full_name="acme/agent-kit", stars=1000, forks=10, open_issues=1)
    older.captured_at = datetime.now(UTC) - timedelta(days=8)
    db.flush()
    repo.record(repo_full_name="acme/agent-kit", stars=1200, forks=12, open_issues=2)
    assert repo.star_delta("acme/agent-kit", days=7) == 200


def test_collect_github_with_mock_api(db: Session) -> None:
    seed_if_empty(db)
    for q in db.query(IntelGithubQuery).all():
        q.enabled = False
    db.add(IntelGithubQuery(name="Agent", query='"ai agent" stars:>50', enabled=True))
    db.flush()

    collector = GithubCollector()

    def fake_get_json(url: str, params: dict | None = None):
        if "search/repositories" in url:
            return SAMPLE_SEARCH, 200
        if "releases/latest" in url:
            return SAMPLE_RELEASE, 200
        return {"_status": 404, "_body": "missing"}, 404

    with patch.object(GithubCollector, "_get_json", side_effect=fake_get_json):
        with patch("bagel.jobs.github.GithubCollector", return_value=collector):
            result = run_collect_github(db)

    assert result["items_found"] >= 1
    assert result["items_created"] >= 1
    assert result["status"] in {JobStatus.SUCCESS, JobStatus.PARTIAL}

    items = db.query(IntelItem).all()
    types = {i.item_type for i in items}
    assert ItemType.GITHUB_REPO in types
    assert any(i.source_type == SourceType.GITHUB for i in items)


def test_github_network_failure_is_failed_with_errors(db: Session) -> None:
    seed_if_empty(db)
    for q in db.query(IntelGithubQuery).all():
        q.enabled = False
    db.add(IntelGithubQuery(name="LLM", query="llm stars:>50", enabled=True))
    db.flush()

    def boom(url: str, params: dict | None = None):
        raise ConnectionError("network unreachable")

    with patch.object(GithubCollector, "_get_json", side_effect=boom):
        result = run_collect_github(db)

    assert result["status"] == JobStatus.FAILED
    assert result["items_created"] == 0
    assert result["errors"]
    assert result.get("error") or result.get("hint")
