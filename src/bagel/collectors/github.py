"""GitHub REST API collector — repos, releases, and star snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from bagel import __version__
from bagel.domain.contracts import NormalizedItem
from bagel.domain.enums import ErrorCode, GithubChangeType, ItemType, SourceType
from bagel.domain.models import IntelGithubQuery
from bagel.integrations.http import build_http_client
from bagel.settings import NetworkMode, Settings, get_settings
from bagel.storage.repositories import canonicalize_url

COLLECTOR_VERSION = __version__
GITHUB_API = "https://api.github.com"


@dataclass
class GithubCollectResult:
    items: list[NormalizedItem] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    http_status: int | None = None
    result_count: int = 0

    @property
    def ok(self) -> bool:
        return self.error_code is None


class GithubCollector:
    """Collect via GitHub REST API only (no HTML scraping)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AI-bagel/0.2",
        }
        token = self.settings.github_token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _get_json(self, url: str, *, params: dict[str, str] | None = None) -> tuple[Any, int]:
        try:
            with build_http_client(self.settings, timeout=45.0) as client:
                resp = client.get(url, params=params, headers=self._headers())
                if resp.status_code in {401, 403, 404, 429}:
                    return {"_status": resp.status_code, "_body": resp.text}, resp.status_code
                resp.raise_for_status()
                return resp.json(), resp.status_code
        except (httpx.HTTPError, OSError):
            if self.settings.network_mode == NetworkMode.AUTO and self.settings.proxy_url:
                with build_http_client(self.settings, timeout=45.0, force_proxy=True) as client:
                    resp = client.get(url, params=params, headers=self._headers())
                    if resp.status_code in {401, 403, 404, 429}:
                        return {"_status": resp.status_code, "_body": resp.text}, resp.status_code
                    resp.raise_for_status()
                    return resp.json(), resp.status_code
            raise

    def search_repos(
        self,
        query: IntelGithubQuery,
        *,
        per_page: int = 20,
        query_override: str | None = None,
    ) -> GithubCollectResult:
        params = {
            "q": query_override or query.query,
            "sort": "updated",
            "order": "desc",
            "per_page": str(per_page),
        }
        url = f"{GITHUB_API}/search/repositories"
        try:
            payload, status = self._get_json(url, params=params)
        except httpx.TimeoutException as exc:
            return GithubCollectResult(
                error_code=ErrorCode.NETWORK_TIMEOUT,
                error_message=str(exc)[:500],
            )
        except (httpx.HTTPError, OSError) as exc:
            return GithubCollectResult(
                error_code=_classify(exc),
                error_message=str(exc)[:500],
            )

        if status == 401:
            return GithubCollectResult(
                error_code=ErrorCode.AUTH_FAILED,
                error_message="GitHub authentication failed",
                http_status=401,
            )
        if status == 429 or (
            status == 403 and "rate limit" in str(payload.get("_body", "")).lower()
        ):
            return GithubCollectResult(
                error_code=ErrorCode.RATE_LIMITED,
                error_message="GitHub rate limited",
                http_status=status,
            )
        if status >= 400:
            return GithubCollectResult(
                error_code=ErrorCode.HTTP_ERROR,
                error_message=str(payload.get("_body", status))[:500],
                http_status=status,
            )

        items: list[NormalizedItem] = []
        snapshots: list[dict[str, Any]] = []
        for repo in payload.get("items", []):
            normalized = _repo_to_item(repo, change_type=GithubChangeType.NEW_REPO)
            if normalized:
                items.append(normalized)
            snapshots.append(
                {
                    "repo_full_name": repo.get("full_name"),
                    "stars": int(repo.get("stargazers_count") or 0),
                    "forks": int(repo.get("forks_count") or 0),
                    "open_issues": int(repo.get("open_issues_count") or 0),
                }
            )

        return GithubCollectResult(
            items=items,
            snapshots=snapshots,
            result_count=int(payload.get("total_count") or len(items)),
            http_status=200,
        )

    def fetch_latest_release(self, full_name: str) -> NormalizedItem | None:
        url = f"{GITHUB_API}/repos/{full_name}/releases/latest"
        try:
            payload, status = self._get_json(url)
        except (httpx.HTTPError, OSError):
            return None
        if status == 404 or status >= 400:
            return None
        return _release_to_item(full_name, payload)


def _repo_to_item(repo: dict[str, Any], *, change_type: str) -> NormalizedItem | None:
    full_name = (repo.get("full_name") or "").strip()
    html_url = (repo.get("html_url") or "").strip()
    if not full_name or not html_url:
        return None
    topics = list(repo.get("topics") or [])
    license_info = repo.get("license") or {}
    metadata = {
        "change_type": change_type,
        "stars": repo.get("stargazers_count"),
        "forks": repo.get("forks_count"),
        "language": repo.get("language"),
        "license": license_info.get("spdx_id") if isinstance(license_info, dict) else None,
        "topics": topics,
        "open_issues": repo.get("open_issues_count"),
        "created_at": repo.get("created_at"),
        "updated_at": repo.get("updated_at"),
        "pushed_at": repo.get("pushed_at"),
        "repo_full_name": full_name,
    }
    return NormalizedItem(
        item_type=ItemType.GITHUB_REPO,
        source_type=SourceType.GITHUB,
        source_id=None,
        title=full_name,
        summary=repo.get("description"),
        content=None,
        url=html_url,
        canonical_url=canonicalize_url(html_url),
        author=repo.get("owner", {}).get("login") if isinstance(repo.get("owner"), dict) else None,
        language=repo.get("language"),
        published_at=_parse_gh_time(
            repo.get("pushed_at") or repo.get("updated_at") or repo.get("created_at")
        ),
        external_id=f"github:repo:{full_name}",
        tags=topics[:20],
        topics=topics[:20],
        metadata=metadata,
        raw_payload=repo,
    )


def _release_to_item(full_name: str, release: dict[str, Any]) -> NormalizedItem | None:
    html_url = (release.get("html_url") or "").strip()
    tag = (release.get("tag_name") or "").strip()
    if not html_url or not tag:
        return None
    return NormalizedItem(
        item_type=ItemType.GITHUB_RELEASE,
        source_type=SourceType.GITHUB,
        source_id=None,
        title=f"{full_name} {tag}",
        summary=(release.get("name") or tag),
        content=release.get("body"),
        url=html_url,
        canonical_url=canonicalize_url(html_url),
        author=(release.get("author") or {}).get("login")
        if isinstance(release.get("author"), dict)
        else None,
        language=None,
        published_at=_parse_gh_time(release.get("published_at") or release.get("created_at")),
        external_id=f"github:release:{full_name}:{tag}",
        tags=["release"],
        topics=[],
        metadata={
            "change_type": GithubChangeType.NEW_RELEASE,
            "repo_full_name": full_name,
            "release": tag,
            "prerelease": bool(release.get("prerelease")),
            "draft": bool(release.get("draft")),
        },
        raw_payload=release,
    )


def _parse_gh_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _classify(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timeout" in msg:
        return ErrorCode.NETWORK_TIMEOUT
    if "connect" in name or "unreachable" in msg or "name or service" in msg:
        return ErrorCode.NETWORK_UNREACHABLE
    if "401" in msg or "403" in msg:
        return ErrorCode.AUTH_FAILED
    if "429" in msg:
        return ErrorCode.RATE_LIMITED
    return ErrorCode.NETWORK_UNREACHABLE
