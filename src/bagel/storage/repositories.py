"""Repositories — transactional persistence for Bagel domain objects.

SQLite is the default backend; PostgreSQL is optional. All collectors and
jobs should write through these repositories so dedup and status rules stay
consistent. Raw collector payloads are stored in `IntelRawEvidence` and must
never be overwritten by LLM fields on `IntelItem`.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Sequence
from urllib.parse import urlparse, urlunparse

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from bagel.domain.enums import ItemStatus, ItemType
from bagel.domain.models import (
    IntelGithubQuery,
    IntelGithubRepoSnapshot,
    IntelItem,
    IntelJobRun,
    IntelKeywordRule,
    IntelRawEvidence,
    IntelSource,
)
from bagel.pipeline.textutil import clip


_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def extract_arxiv_id(text: str | None) -> str | None:
    """Pull a bare arXiv id (e.g. ``2401.12345``) from a URL or free text."""
    if not text:
        return None
    m = _ARXIV_ID_RE.search(text)
    return m.group(1).lower() if m else None


def extract_doi(text: str | None) -> str | None:
    """Normalize a DOI string, stripping resolver prefixes when present."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^https?://(dx\.)?doi\.org/", "", cleaned, flags=re.I)
    m = _DOI_RE.search(cleaned)
    if not m:
        return None
    doi = m.group(0).rstrip(".").lower()
    # Collapse figshare/zenodo version suffixes like .1 / .2 for soft identity
    doi = re.sub(r"(\.\d+)$", "", doi) if "/zenodo." not in doi and "zenodo." not in doi else doi
    return doi


def canonicalize_url(url: str) -> str:
    """Stable URL key used for upsert / uniqueness (strips tracking params)."""
    raw = (url or "").strip()
    parsed = urlparse(raw)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    scheme = (parsed.scheme or "https").lower()

    # Cross-source paper identity: HF daily papers ↔ arXiv abs (drop version)
    arxiv_id = extract_arxiv_id(raw)
    if arxiv_id and (
        "arxiv.org" in netloc
        or ("huggingface.co" in netloc and "/papers/" in path)
        or raw.lower().startswith("arxiv:")
    ):
        return f"https://arxiv.org/abs/{arxiv_id}"

    doi = extract_doi(raw)
    if doi and ("doi.org" in netloc or path.startswith("/10.") or raw.lower().startswith("10.")):
        return f"https://doi.org/{doi}"

    # Drop tracking query params commonly used in feeds
    return urlunparse((scheme, netloc, path, "", "", ""))


def normalize_title(title: str) -> str:
    """Lowercase + collapse whitespace for title-based hashing."""
    t = title.strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def content_hash(canonical_url: str, title: str) -> str:
    """SHA-256 of canonical URL + normalized title (secondary uniqueness key)."""
    payload = f"{canonical_url}|{normalize_title(title)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def paper_identity_hash(
    *,
    url: str,
    title: str,
    external_id: str | None = None,
) -> str:
    """Stable hash so arXiv/HF and same-title OpenAlex near-dupes upsert together."""
    ext = (external_id or "").strip()
    arxiv_id = extract_arxiv_id(ext) or extract_arxiv_id(url)
    if arxiv_id:
        key = f"paper:arxiv:{arxiv_id}"
    else:
        # Prefer title identity for papers: OpenAlex often lists multiple deposits
        # with the same display_name but different zenodo DOIs / work IDs.
        key = f"paper:title:{normalize_title(title)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def raw_hash(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, dict):
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    else:
        raw = payload
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SourceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_enabled(self) -> Sequence[IntelSource]:
        return self.session.scalars(
            select(IntelSource).where(IntelSource.enabled.is_(True)).order_by(IntelSource.priority)
        ).all()

    def list_all(self) -> Sequence[IntelSource]:
        return self.session.scalars(select(IntelSource).order_by(IntelSource.priority)).all()

    def get(self, source_id: uuid.UUID) -> IntelSource | None:
        return self.session.get(IntelSource, source_id)

    def add(self, source: IntelSource) -> IntelSource:
        self.session.add(source)
        self.session.flush()
        return source

    def delete(self, source: IntelSource) -> None:
        self.session.delete(source)
        self.session.flush()

    def mark_success(self, source: IntelSource) -> None:
        source.last_success_at = datetime.now(UTC)
        source.last_error_at = None
        source.last_error_code = None

    def mark_error(self, source: IntelSource, error_code: str) -> None:
        source.last_error_at = datetime.now(UTC)
        source.last_error_code = error_code


class KeywordRuleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_enabled(self) -> Sequence[IntelKeywordRule]:
        return self.session.scalars(
            select(IntelKeywordRule).where(IntelKeywordRule.enabled.is_(True))
        ).all()

    def list_all(self) -> Sequence[IntelKeywordRule]:
        return self.session.scalars(
            select(IntelKeywordRule).order_by(
                IntelKeywordRule.rule_type, IntelKeywordRule.keyword
            )
        ).all()

    def list_by_type(self, rule_type: str) -> Sequence[IntelKeywordRule]:
        return self.session.scalars(
            select(IntelKeywordRule)
            .where(IntelKeywordRule.rule_type == rule_type)
            .order_by(IntelKeywordRule.keyword)
        ).all()

    def find_by_keyword(self, keyword: str, rule_type: str | None = None) -> IntelKeywordRule | None:
        stmt = select(IntelKeywordRule).where(IntelKeywordRule.keyword == keyword)
        if rule_type:
            stmt = stmt.where(IntelKeywordRule.rule_type == rule_type)
        return self.session.scalar(stmt)

    def get(self, rule_id: uuid.UUID) -> IntelKeywordRule | None:
        return self.session.get(IntelKeywordRule, rule_id)

    def add(self, rule: IntelKeywordRule) -> IntelKeywordRule:
        self.session.add(rule)
        self.session.flush()
        return rule

    def delete(self, rule: IntelKeywordRule) -> None:
        self.session.delete(rule)
        self.session.flush()


class GithubQueryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_enabled(self) -> Sequence[IntelGithubQuery]:
        return self.session.scalars(
            select(IntelGithubQuery).where(IntelGithubQuery.enabled.is_(True))
        ).all()

    def add(self, query: IntelGithubQuery) -> IntelGithubQuery:
        self.session.add(query)
        self.session.flush()
        return query

    def mark_run(self, query: IntelGithubQuery, *, result_count: int, error: str | None = None) -> None:
        from datetime import datetime, UTC
        query.last_run_at = datetime.now(UTC)
        query.last_result_count = result_count
        query.last_error = error
        self.session.flush()


class RawEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        source_type: str,
        source_url: str | None,
        external_id: str | None,
        raw_payload: dict[str, Any],
        http_status: int | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        collector_version: str | None = None,
    ) -> IntelRawEvidence:
        evidence = IntelRawEvidence(
            source_type=source_type,
            source_url=source_url,
            external_id=clip(external_id, 512),
            raw_payload=raw_payload,
            raw_hash=raw_hash(raw_payload),
            http_status=http_status,
            etag=clip(etag, 255),
            last_modified=clip(last_modified, 255),
            collector_version=clip(collector_version, 32),
        )
        self.session.add(evidence)
        self.session.flush()
        return evidence


class ItemRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_by_canonical_url(self, canonical_url: str) -> IntelItem | None:
        return self.session.scalar(
            select(IntelItem).where(IntelItem.canonical_url == canonical_url)
        )

    def find_by_content_hash(self, hash_value: str) -> IntelItem | None:
        return self.session.scalar(select(IntelItem).where(IntelItem.content_hash == hash_value))

    def find_paper_by_normalized_title(self, title: str) -> IntelItem | None:
        """Fallback match for legacy rows that predate paper identity hashes."""
        needle = normalize_title(title)
        if not needle:
            return None
        # Prefer favorites / oldest when multiple already exist.
        rows = self.session.scalars(
            select(IntelItem)
            .where(IntelItem.item_type == ItemType.PAPER)
            .order_by(
                IntelItem.is_favorite.desc(),
                IntelItem.is_top.desc(),
                IntelItem.first_seen_at.asc(),
            )
        ).all()
        for row in rows:
            if normalize_title(row.title or "") == needle:
                return row
        return None

    def get(self, item_id: uuid.UUID) -> IntelItem | None:
        return self.session.get(IntelItem, item_id)

    @staticmethod
    def _platform_clause(platform: str):
        """Match media platform from metadata.platform (preferred) or tags."""
        code = (platform or "").strip()
        if not code:
            return None
        meta_plat = cast(IntelItem.metadata_["platform"], String)
        # tags is a JSON array; platform code is also stored as first tag on ingest
        tag_match = cast(IntelItem.tags, String).like(f'%"{code}"%')
        return or_(meta_plat == code, tag_match)

    def _status_filter(
        self,
        status: str | Sequence[str],
        *,
        item_type: str | None = None,
        category: str | None = None,
        platform: str | None = None,
        owner_id=None,
    ):
        statuses = [status] if isinstance(status, str) else list(status)
        stmt = select(IntelItem).where(IntelItem.status.in_(statuses))
        if item_type:
            stmt = stmt.where(IntelItem.item_type == item_type)
        if category:
            stmt = stmt.where(IntelItem.category == category)
        plat = self._platform_clause(platform or "")
        if plat is not None:
            stmt = stmt.where(plat)
        if owner_id is not None:
            stmt = stmt.where(IntelItem.owner_id == owner_id)
        return stmt

    def list_by_status(
        self,
        status: str | Sequence[str],
        *,
        item_type: str | None = None,
        category: str | None = None,
        platform: str | None = None,
        owner_id=None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[IntelItem]:
        stmt = (
            self._status_filter(
                status,
                item_type=item_type,
                category=category,
                platform=platform,
                owner_id=owner_id,
            )
            .order_by(
                func.coalesce(IntelItem.published_at, IntelItem.first_seen_at).desc(),
                IntelItem.score.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return self.session.scalars(stmt).all()

    def count_by_status(
        self,
        status: str | Sequence[str],
        *,
        item_type: str | None = None,
        category: str | None = None,
        platform: str | None = None,
        owner_id=None,
    ) -> int:
        statuses = [status] if isinstance(status, str) else list(status)
        stmt = select(func.count()).select_from(IntelItem).where(IntelItem.status.in_(statuses))
        if item_type:
            stmt = stmt.where(IntelItem.item_type == item_type)
        if category:
            stmt = stmt.where(IntelItem.category == category)
        plat = self._platform_clause(platform or "")
        if plat is not None:
            stmt = stmt.where(plat)
        if owner_id is not None:
            stmt = stmt.where(IntelItem.owner_id == owner_id)
        return int(self.session.scalar(stmt) or 0)

    def list_categories(
        self,
        status: str | Sequence[str],
        *,
        item_type: str | None = None,
        platform: str | None = None,
        owner_id=None,
    ) -> Sequence[str]:
        statuses = [status] if isinstance(status, str) else list(status)
        stmt = (
            select(IntelItem.category)
            .where(
                IntelItem.status.in_(statuses),
                IntelItem.category.is_not(None),
            )
            .distinct()
            .order_by(IntelItem.category)
        )
        if item_type:
            stmt = stmt.where(IntelItem.item_type == item_type)
        plat = self._platform_clause(platform or "")
        if plat is not None:
            stmt = stmt.where(plat)
        if owner_id is not None:
            stmt = stmt.where(IntelItem.owner_id == owner_id)
        return [c for c in self.session.scalars(stmt).all() if c]

    def list_favorites(
        self,
        *,
        category: str | None = None,
        item_types: list[str] | None = None,
        platform: str | None = None,
        owner_id=None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[IntelItem]:
        stmt = select(IntelItem).where(IntelItem.is_favorite.is_(True))
        if category:
            stmt = stmt.where(IntelItem.category == category)
        if item_types:
            stmt = stmt.where(IntelItem.item_type.in_(item_types))
        plat = self._platform_clause(platform or "")
        if plat is not None:
            stmt = stmt.where(plat)
        if owner_id is not None:
            stmt = stmt.where(IntelItem.owner_id == owner_id)
        stmt = stmt.order_by(
            func.coalesce(IntelItem.published_at, IntelItem.updated_at).desc()
        ).offset(offset).limit(limit)
        return self.session.scalars(stmt).all()

    def count_favorites(
        self,
        *,
        category: str | None = None,
        item_types: list[str] | None = None,
        platform: str | None = None,
        owner_id=None,
    ) -> int:
        stmt = select(func.count()).select_from(IntelItem).where(IntelItem.is_favorite.is_(True))
        if category:
            stmt = stmt.where(IntelItem.category == category)
        if item_types:
            stmt = stmt.where(IntelItem.item_type.in_(item_types))
        plat = self._platform_clause(platform or "")
        if plat is not None:
            stmt = stmt.where(plat)
        if owner_id is not None:
            stmt = stmt.where(IntelItem.owner_id == owner_id)
        return int(self.session.scalar(stmt) or 0)

    def upsert_from_normalized(
        self,
        *,
        item_type: str,
        source_type: str,
        source_id: uuid.UUID | None,
        title: str,
        url: str,
        summary: str | None = None,
        content: str | None = None,
        author: str | None = None,
        language: str | None = None,
        published_at: datetime | None = None,
        tags: list[str] | None = None,
        topics: list[str] | None = None,
        category: str | None = None,
        metadata: dict[str, Any] | None = None,
        raw_evidence_id: uuid.UUID | None = None,
        status: str = ItemStatus.CANDIDATE,
        score: float = 0.0,
        owner_id: uuid.UUID | None = None,
    ) -> tuple[IntelItem, bool]:
        """Insert or refresh an item. Returns (item, created)."""
        canonical = canonicalize_url(url)
        meta = dict(metadata or {})
        external_id = str(meta.get("external_id") or "") or None
        if item_type == ItemType.PAPER:
            digest = paper_identity_hash(url=url, title=title, external_id=external_id)
        else:
            digest = content_hash(canonical, title)
        now = datetime.now(UTC)
        author = clip(author, 255)
        language = clip(language, 16)
        category = clip(category, 64)

        existing = self.find_by_canonical_url(canonical) or self.find_by_content_hash(digest)
        if existing is None and item_type == ItemType.PAPER:
            existing = self.find_paper_by_normalized_title(title)
        if existing:
            existing.last_seen_at = now
            existing.title = title
            # Migrate legacy paper hashes / prefer stable arxiv URL when merging.
            if existing.content_hash != digest:
                existing.content_hash = digest
            if item_type == ItemType.PAPER:
                old_c = canonicalize_url(existing.url or "")
                new_c = canonical
                if "arxiv.org/abs/" in new_c and "arxiv.org/abs/" not in old_c:
                    existing.url = url
                    existing.canonical_url = canonical
            if owner_id is not None and existing.owner_id is None:
                existing.owner_id = owner_id
            if summary:
                existing.summary = summary
            if content:
                existing.content = content
            if published_at is not None:
                # Always refresh source publish time so lists stay ordered by freshness.
                existing.published_at = published_at
            if metadata:
                existing.metadata_ = {**(existing.metadata_ or {}), **metadata}
            if tags:
                existing.tags = list({*(existing.tags or []), *tags})
            if category:
                existing.category = category
            if author is not None:
                existing.author = author
            if language is not None:
                existing.language = language
            if topics:
                existing.topics = list({*(existing.topics or []), *topics})
            # Refresh ranking signals on re-collect without un-rejecting.
            if existing.status != ItemStatus.REJECTED:
                existing.score = float(score)
            self.session.flush()
            return existing, False

        item = IntelItem(
            item_type=item_type,
            source_type=source_type,
            source_id=source_id,
            owner_id=owner_id,
            title=title,
            summary=summary,
            content=content,
            url=url,
            canonical_url=canonical,
            author=author,
            language=language,
            published_at=published_at,
            content_hash=digest,
            status=status,
            score=score,
            tags=tags or [],
            topics=topics or [],
            category=category,
            metadata_=metadata or {},
            raw_evidence_id=raw_evidence_id,
            first_seen_at=now,
            last_seen_at=now,
        )
        self.session.add(item)
        self.session.flush()
        return item, True

    def set_status(self, item: IntelItem, status: str) -> IntelItem:
        item.status = status
        self.session.flush()
        return item

    def set_flags(
        self,
        item: IntelItem,
        *,
        is_favorite: bool | None = None,
        is_top: bool | None = None,
        is_deep_read: bool | None = None,
    ) -> IntelItem:
        if is_favorite is not None:
            # Favorite is a flag only — keep status so list pages do not shrink.
            item.is_favorite = is_favorite
        if is_top is not None:
            item.is_top = is_top
        if is_deep_read is not None:
            item.is_deep_read = is_deep_read
        self.session.flush()
        return item

    def dedupe_papers(self) -> dict[str, int]:
        """
        Delete dirty duplicate PAPER rows.

        Keep one per identity (arxiv id, else normalized title). Prefer favorite/top,
        then arxiv.org URL, then earliest first_seen.
        """
        papers = list(
            self.session.scalars(
                select(IntelItem).where(IntelItem.item_type == ItemType.PAPER)
            ).all()
        )
        groups: dict[str, list[IntelItem]] = {}
        for item in papers:
            ext = str((item.metadata_ or {}).get("external_id") or "")
            aid = extract_arxiv_id(ext) or extract_arxiv_id(item.url or "")
            key = f"arxiv:{aid}" if aid else f"title:{normalize_title(item.title or '')}"
            groups.setdefault(key, []).append(item)

        deleted = 0
        kept = 0

        def _rank(it: IntelItem) -> tuple:
            url = (it.url or "").lower()
            return (
                0 if it.is_favorite else 1,
                0 if it.is_top else 1,
                0 if "arxiv.org/abs/" in url else 1,
                it.first_seen_at or it.created_at,
            )

        for items in groups.values():
            if len(items) == 1:
                kept += 1
                winner = items[0]
                digest = paper_identity_hash(
                    url=winner.url,
                    title=winner.title,
                    external_id=str((winner.metadata_ or {}).get("external_id") or "") or None,
                )
                if winner.content_hash != digest:
                    # Avoid unique collisions: only rewrite when no other row holds digest.
                    other = self.find_by_content_hash(digest)
                    if other is None or other.id == winner.id:
                        winner.content_hash = digest
                continue
            items_sorted = sorted(items, key=_rank)
            winner = items_sorted[0]
            kept += 1
            for loser in items_sorted[1:]:
                self.session.delete(loser)
                deleted += 1
            self.session.flush()
            digest = paper_identity_hash(
                url=winner.url,
                title=winner.title,
                external_id=str((winner.metadata_ or {}).get("external_id") or "") or None,
            )
            winner.content_hash = digest
            winner.canonical_url = canonicalize_url(winner.url)
        self.session.flush()
        return {"kept": kept, "deleted": deleted, "groups": len(groups)}


class JobRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start(self, job_name: str) -> IntelJobRun:
        run = IntelJobRun(job_name=job_name, status="RUNNING")
        self.session.add(run)
        self.session.flush()
        return run

    def finish(
        self,
        run: IntelJobRun,
        *,
        status: str,
        items_found: int = 0,
        items_created: int = 0,
        items_updated: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> IntelJobRun:
        run.finished_at = datetime.now(UTC)
        run.status = status
        run.items_found = items_found
        run.items_created = items_created
        run.items_updated = items_updated
        run.error_code = error_code
        run.error_message = error_message
        self.session.flush()
        return run


class GithubSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, *, repo_full_name: str, stars: int, forks: int, open_issues: int) -> IntelGithubRepoSnapshot:
        from datetime import datetime, UTC
        snap = IntelGithubRepoSnapshot(
            repo_full_name=repo_full_name,
            stars=stars,
            forks=forks,
            open_issues=open_issues,
            captured_at=datetime.now(UTC),
        )
        self.session.add(snap)
        self.session.flush()
        return snap

    def latest(self, repo_full_name: str) -> IntelGithubRepoSnapshot | None:
        return self.session.scalars(
            select(IntelGithubRepoSnapshot)
            .where(IntelGithubRepoSnapshot.repo_full_name == repo_full_name)
            .order_by(IntelGithubRepoSnapshot.captured_at.desc())
            .limit(1)
        ).first()

    def star_delta(self, repo_full_name: str, *, days: int = 7) -> int | None:
        from datetime import datetime, UTC, timedelta
        latest = self.latest(repo_full_name)
        if latest is None:
            return None
        cutoff = datetime.now(UTC) - timedelta(days=days)
        older = self.session.scalars(
            select(IntelGithubRepoSnapshot)
            .where(
                IntelGithubRepoSnapshot.repo_full_name == repo_full_name,
                IntelGithubRepoSnapshot.captured_at <= cutoff,
            )
            .order_by(IntelGithubRepoSnapshot.captured_at.desc())
            .limit(1)
        ).first()
        if older is None:
            return None
        return int(latest.stars) - int(older.stars)
